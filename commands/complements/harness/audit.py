"""Auditoria de remoção/migração com ledger de completude (M3)."""

import json
import os
import re
from datetime import datetime

from . import graphdb, manifest
from commands.complements.harness_core.runner import run_process
from commands.complements.harness_core.util import as_bool, legacy_repo, slugify, workspace
from .tasks.jit import rg_bin

CLASSES = (
    "schema-object",
    "embedded-sql",
    "include-entrypoint",
    "php-reference",
    "config-deploy",
    "docs",
    "tests",
    "unknown-hit",
)
CONFIG_EXTS = {".env", ".ini", ".conf", ".yml", ".yaml", ".toml", ".properties"}
CODE_EXTS = {".php", ".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".cs", ".rb", ".go"}
SQL_EXTS = {".sql"}


def _audits_dir(ctx) -> str:
    configured = ((ctx.config or {}).get("audit") or {}).get("ledgers_path")
    if configured:
        from commands.complements.harness_core.config import resolve_path

        return os.path.abspath(resolve_path(ctx.config, str(configured)))
    return os.path.join(workspace(ctx), "knowledge", "audits")


def ledger_path(ctx, target: str, write: str | None = None) -> str:
    if write:
        return os.path.abspath(
            write
            if os.path.isabs(write)
            else os.path.join(_audits_dir(ctx), os.path.basename(write))
        )
    return os.path.join(_audits_dir(ctx), f"{slugify(target)}-removal.json")


def _rg_hits(ctx, matchers: list[str]) -> tuple[list[dict], str]:
    binary = rg_bin(ctx)
    if not binary:
        return [], "ripgrep (rg) não encontrado"
    pattern = "|".join(re.escape(item) for item in matchers if item)
    if not pattern:
        return [], "sem matchers"
    cmd = [
        binary,
        "-n",
        "--no-ignore",
        "--max-columns",
        "500",
        "--glob",
        "!**/.git/**",
        "--glob",
        "!**/node_modules/**",
        "--glob",
        "!**/vendor/**",
        "--glob",
        "!**/dist/**",
        "--glob",
        "!**/build/**",
        "--glob",
        "!**/__pycache__/**",
        pattern,
    ]
    result = run_process(cmd, cwd=legacy_repo(ctx), timeout=120)
    if result.exit_code not in (0, 1):
        return [], result.stderr.strip() or "falha no ripgrep"
    hits = []
    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        path, number, text = parts
        try:
            line_no = int(number)
        except ValueError:
            continue
        hits.append({"path": path.replace("\\", "/"), "line": line_no, "text": text.strip()})
    return hits, ""


def _classify(path: str) -> str:
    lower = path.lower().replace("\\", "/")
    ext = os.path.splitext(lower)[1]
    base = os.path.basename(lower)
    if lower.startswith(("docs/", "manuais/", "tickets/")) or ext == ".md":
        return "docs"
    if "/tests/" in f"/{lower}" or base.startswith("test_") or base.endswith(("_test.py", "test.php")):
        return "tests"
    if ext in CONFIG_EXTS or base.startswith((".env", "docker-compose")) or base == "dockerfile":
        return "config-deploy"
    if ext in SQL_EXTS:
        return "schema-object"
    if ext in CODE_EXTS:
        return "php-reference"
    return "unknown-hit"


def _table_facts(ctx, target: str):
    conn = graphdb.connect(ctx)
    try:
        exists = conn.execute("SELECT name FROM tables WHERE name=?", (target,)).fetchone()
        ops = [dict(row) for row in conn.execute("SELECT * FROM table_ops WHERE table_name=?", (target,)).fetchall()]
        fks = [dict(row) for row in conn.execute("SELECT * FROM fk_inferred WHERE from_table=? OR to_table=?", (target, target)).fetchall()]
        includes = [dict(row) for row in conn.execute("SELECT * FROM includes").fetchall()]
        return bool(exists), ops, fks, includes
    finally:
        conn.close()


def collect(ctx, target: str, matchers: list[str]) -> tuple[list[dict], list[str]]:
    """Executa as classes e devolve ``(classes, avisos)``."""
    findings = []
    hits, error = _rg_hits(ctx, matchers)
    if error:
        findings.append(error)
    table_exists, ops, fks, includes = _table_facts(ctx, target)
    embedded = {
        (op["file_path"], int(op["line"] or 0))
        for op in ops
    }
    buckets = {name: [] for name in CLASSES}
    for hit in hits:
        bucket = _classify(hit["path"])
        buckets[bucket].append(hit)

    if table_exists:
        buckets["schema-object"].append({
            "path": "(store)",
            "line": 0,
            "text": f"tabela {target} existe; {len(ops)} operação(ões); {len(fks)} FK(s)",
        })
    for op in ops:
        buckets["embedded-sql"].append({
            "path": op["file_path"],
            "line": int(op["line"] or 0),
            "text": f"{op.get('op')} ({op.get('access')}) {op.get('sql') or ''}".strip(),
        })
    for inc in includes:
        target_path = str(inc.get("target_path") or "")
        base = os.path.basename(target_path)
        if any(os.path.basename(op["file_path"]) == base for op in ops):
            buckets["include-entrypoint"].append({
                "path": inc.get("file_path") or "",
                "line": int(inc.get("line") or 0),
                "text": f"{inc.get('kind')} {target_path}",
            })

    classes = []
    for name in CLASSES:
        active = buckets[name]
        classes.append({
            "class": name,
            "status": "found" if active else "not-found",
            "active": active[:50],
            "retained": [],
            "unknown": [],
            "verification": {
                "method": "store+rg" if name in ("schema-object", "embedded-sql") else "rg",
                "query": target,
                "result_count": len(active),
                "truncated": len(active) > 50,
            },
        })
    return classes, findings


def _ledger(ctx, target: str, matchers: list[str], kind: str) -> dict:
    classes, findings = collect(ctx, target, matchers)
    state = manifest.git_state(legacy_repo(ctx))
    active = sum(len(item["active"]) for item in classes)
    unknown = sum(len(item["active"]) for item in classes if item["class"] == "unknown-hit")
    status = "needs-review" if unknown else ("found" if active else "clean")
    return {
        "schema": "harness.audit-ledger.v1",
        "id": f"{slugify(target)}-{kind}",
        "kind": kind,
        "target": {"raw": target, "matchers": matchers},
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "snapshot": {
            "commit": state.get("commit"),
            "branch": state.get("branch"),
            "dirty": state.get("dirty"),
            "manifest_hash": manifest.hash_file(manifest.manifest_path(ctx)),
        },
        "classes": classes,
        "verdict": {"status": status, "blockers": findings + [f"{unknown} hit(s) desconhecido(s)"] if unknown else findings},
    }


def create(ctx, target: str, kind: str = "removal", matchers=None, write=None) -> dict:
    matchers = [str(item).strip() for item in (matchers or []) if str(item).strip()] or [target]
    ledger = _ledger(ctx, target, matchers, kind)
    path = ledger_path(ctx, target, write)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(ledger, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(temp, path)
    ledger["path"] = path
    return ledger


def load(ctx, path: str | None = None) -> tuple[dict | None, str | None]:
    if path:
        target = os.path.abspath(path)
    else:
        folder = _audits_dir(ctx)
        candidates = sorted(
            (os.path.join(folder, name) for name in os.listdir(folder) if name.endswith(".json")),
            key=os.path.getmtime,
        ) if os.path.isdir(folder) else []
        if not candidates:
            return None, None
        target = candidates[-1]
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, target
    return data if isinstance(data, dict) else None, target


def verify(ctx, path: str | None = None, fail_on_leftovers: bool = False) -> dict:
    ledger, resolved = load(ctx, path)
    if not ledger:
        return {"ok": False, "status": "unknown", "reasons": ["ledger não encontrado"], "path": resolved}
    target = str((ledger.get("target") or {}).get("raw") or "")
    matchers = (ledger.get("target") or {}).get("matchers") or [target]
    current, findings = collect(ctx, target, matchers)
    prior = {item["class"]: item for item in ledger.get("classes") or []}
    classes = []
    for item in current:
        before = prior.get(item["class"]) or {}
        active = item["active"]
        if active:
            status = "found"
        elif before.get("status") in ("found", "needs-review"):
            status = "removed"
        else:
            status = "not-found"
        item["status"] = status
        item["retained"] = before.get("retained") or []
        classes.append(item)
    active_count = sum(len(item["active"]) for item in classes)
    unknown = sum(len(item["active"]) for item in classes if item["class"] == "unknown-hit")
    status = "needs-review" if unknown else ("found" if active_count else "clean")
    ok = status == "clean" or not fail_on_leftovers
    return {
        "ok": ok,
        "status": status,
        "path": resolved,
        "target": target,
        "classes": classes,
        "reasons": findings,
        "fail_on_leftovers": bool(fail_on_leftovers),
    }


def describe_ledger(ledger: dict) -> str:
    lines = [
        f"ledger: {ledger.get('path') or ledger.get('id')}",
        f"alvo: {ledger['target']['raw']} (matchers: {', '.join(ledger['target']['matchers'])})",
        f"veredito: {ledger['verdict']['status']}",
        "classes:",
    ]
    for item in ledger.get("classes") or []:
        lines.append(
            f"- {item['class']}: {item['status']} ({item['verification']['result_count']})"
        )
        for hit in (item.get("active") or [])[:5]:
            lines.append(f"  - {hit.get('path')}:{hit.get('line')} {hit.get('text')}")
    if ledger["verdict"].get("blockers"):
        lines.append("bloqueios:")
        lines.extend(f"- {item}" for item in ledger["verdict"]["blockers"])
    return "\n".join(lines)


def describe_verify(data: dict) -> str:
    lines = [
        f"verificação: {data['status']}",
        f"ledger: {data.get('path')}",
        f"alvo: {data.get('target')}",
        "classes:",
    ]
    for item in data.get("classes") or []:
        lines.append(f"- {item['class']}: {item['status']} ({item['verification']['result_count']})")
        for hit in (item.get("active") or [])[:5]:
            lines.append(f"  - {hit.get('path')}:{hit.get('line')} {hit.get('text')}")
    if data.get("reasons"):
        lines.append("avisos:")
        lines.extend(f"- {item}" for item in data["reasons"])
    return "\n".join(lines)
