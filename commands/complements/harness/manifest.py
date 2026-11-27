"""Manifesto de frescor dos artefatos de mapeamento (M0)."""

import hashlib
import json
import os
import subprocess
from datetime import datetime

from commands.complements.harness_core.util import legacy_repo, workspace

SCHEMA = "harness.manifest.v1"
MANIFEST_REL = "knowledge/manifest.json"


def manifest_path(ctx) -> str:
    return os.path.join(workspace(ctx), "knowledge", "manifest.json")


def hash_file(path: str) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return ""


def _git(repo: str, *args):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def git_state(repo: str) -> dict:
    """Commit, branch e dirty; aceita repositório legado dentro de um repo git maior."""
    repo = os.path.abspath(repo)
    toplevel = (_git(repo, "rev-parse", "--show-toplevel") or "").strip()
    if not toplevel:
        return {
            "available": False,
            "root": repo,
            "git_root": "",
            "branch": "",
            "commit": "",
            "dirty": False,
            "dirty_files": [],
        }

    branch = (_git(toplevel, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    commit = (_git(toplevel, "rev-parse", "HEAD") or "").strip()
    status = (_git(toplevel, "status", "--porcelain") or "").splitlines()
    dirty_files = [line[3:].strip() for line in status if line.strip()]
    return {
        "available": bool(commit),
        "root": repo,
        "git_root": toplevel,
        "branch": branch,
        "commit": commit,
        "dirty": bool(dirty_files),
        "dirty_files": dirty_files,
    }


def inputs_from_index(ctx, files_index: dict) -> list[dict]:
    """Entradas do manifesto a partir do ``files_index`` do esqueleto."""
    repo = legacy_repo(ctx)
    inputs = []
    for rel, info in sorted(files_index.items()):
        path = os.path.join(repo, rel)
        exists = os.path.isfile(path)
        stat = os.stat(path) if exists else None
        inputs.append(
            {
                "path": rel.replace("\\", "/"),
                "size": int(info.get("size") or (stat.st_size if stat else 0)),
                "mtime": int(info.get("mtime") or (int(stat.st_mtime) if stat else 0)),
                "hash": hash_file(path) if exists else "",
            }
        )
    return inputs


def artifact(rel: str, path: str, **meta) -> dict:
    entry = {
        "path": rel.replace("\\", "/"),
        "hash": hash_file(path),
        "size": os.path.getsize(path) if os.path.isfile(path) else 0,
    }
    entry.update(meta)
    return entry


def _atomic_write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(temp, path)


def read_manifest(ctx) -> dict | None:
    path = manifest_path(ctx)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_manifest(ctx, artifacts: dict[str, dict], inputs: list[dict], profile: str, parser_version: int) -> str:
    """Grava o manifesto completo (``artifacts`` = ``rel -> meta``)."""
    repo = legacy_repo(ctx)
    ws = workspace(ctx)
    entries = {
        rel: artifact(rel, os.path.join(ws, rel), **(meta or {}))
        for rel, meta in artifacts.items()
    }
    data = {
        "schema": SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scanner": {
            "name": "harness",
            "profile": profile,
            "parser_version": int(parser_version or 0),
        },
        "repo": git_state(repo),
        "artifacts": entries,
        "inputs": inputs,
    }
    path = manifest_path(ctx)
    _atomic_write(path, data)
    return path


def update(ctx, rel: str, path: str, **meta) -> str:
    """Atualiza um artefato preservando entradas existentes (ex.: após ``db:links``)."""
    info = read_manifest(ctx) or {
        "schema": SCHEMA,
        "scanner": {"name": "harness", "profile": "", "parser_version": 0},
        "artifacts": {},
        "inputs": [],
    }
    info.setdefault("artifacts", {})[rel] = artifact(rel, path, **meta)
    info["generated_at"] = datetime.now().isoformat(timespec="seconds")
    info["repo"] = git_state(legacy_repo(ctx))
    info["schema"] = SCHEMA
    path_out = manifest_path(ctx)
    _atomic_write(path_out, info)
    return path_out


def verify(ctx, deep: bool = False, fail_on_dirty: bool = False) -> dict:
    """Compara o manifesto com o repositório e os artefatos atuais."""
    info = read_manifest(ctx)
    if not info:
        return {
            "schema": SCHEMA,
            "status": "unknown",
            "ok": False,
            "reasons": ["manifesto ausente: rode `code:skeleton`"],
            "manifest": manifest_path(ctx),
            "repo": git_state(legacy_repo(ctx)),
        }

    repo = os.path.abspath(legacy_repo(ctx))
    ws = workspace(ctx)
    current = git_state(repo)
    reasons: list[str] = []
    stale = False

    saved = info.get("repo") or {}
    if saved.get("root") and os.path.abspath(str(saved["root"])) != repo:
        stale = True
        reasons.append(f"repositório mudou: {saved.get('root')} -> {repo}")
    if saved.get("commit") and current.get("commit") and saved["commit"] != current["commit"]:
        stale = True
        reasons.append(f"commit mudou: {saved['commit'][:8]} -> {current['commit'][:8]}")

    for item in info.get("inputs") or []:
        rel = str(item.get("path") or "")
        path = os.path.join(repo, rel)
        if not os.path.isfile(path):
            stale = True
            reasons.append(f"arquivo removido: {rel}")
            continue
        stat = os.stat(path)
        if int(item.get("size") or 0) != stat.st_size:
            stale = True
            reasons.append(f"tamanho mudou: {rel}")
        elif not deep and int(item.get("mtime") or 0) != int(stat.st_mtime):
            stale = True
            reasons.append(f"mtime mudou: {rel}")
        elif deep and item.get("hash") and item["hash"] != hash_file(path):
            stale = True
            reasons.append(f"conteúdo mudou: {rel}")

    for rel, meta in (info.get("artifacts") or {}).items():
        path = os.path.join(ws, rel)
        if not os.path.isfile(path):
            stale = True
            reasons.append(f"artefato removido: {rel}")
        elif meta.get("hash") and meta["hash"] != hash_file(path):
            stale = True
            reasons.append(f"artefato alterado: {rel}")

    if stale:
        status = "stale"
    elif not current.get("available"):
        status = "unknown"
        reasons.append("repositório sem git: não é possível verificar o commit")
    elif current.get("dirty"):
        status = "dirty"
        reasons.append(f"worktree sujo ({len(current.get('dirty_files') or [])} arquivo(s))")
    else:
        status = "fresh"

    ok = status == "fresh" or (status == "dirty" and not fail_on_dirty)
    return {
        "schema": SCHEMA,
        "status": status,
        "ok": ok,
        "deep": bool(deep),
        "generated_at": info.get("generated_at"),
        "manifest": manifest_path(ctx),
        "repo": current,
        "reasons": reasons,
    }


def describe(data: dict) -> str:
    repo = data.get("repo") or {}
    lines = [
        f"frescor: {data.get('status')}",
        f"manifesto: {data.get('manifest')}",
        f"gerado em: {data.get('generated_at') or '(desconhecido)'}",
        f"commit: {repo.get('commit') or '(sem git)'} "
        f"({repo.get('branch') or '-'})",
    ]
    reasons = data.get("reasons") or []
    if reasons:
        lines.append("motivos:")
        lines.extend(f"- {reason}" for reason in reasons)
    return "\n".join(lines)


def warning(data: dict | None) -> str:
    if not data:
        return ""
    status = data.get("status")
    if status == "fresh":
        return ""
    if status == "stale":
        reasons = "; ".join(data.get("reasons") or [])
        return f"AVISO: mapa stale — {reasons}. Rode `code:skeleton`."
    if status == "dirty":
        return "AVISO: worktree sujo; o mapa pode não refletir o estado atual."
    if status == "unknown":
        reasons = "; ".join(data.get("reasons") or [])
        return f"AVISO: frescor desconhecido — {reasons}."
    return ""
