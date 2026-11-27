"""Montagem do `code:brief`: pacote de contexto ancorado (M2)."""

import math
import os
import re
import subprocess
from datetime import datetime

from . import graphdb, manifest
from commands.complements.harness_core import redact
from commands.complements.harness_core.util import as_bool, as_int, legacy_repo


def _settings(ctx):
    cfg = ctx.config.get("brief") or {}
    output = ctx.config.get("output") or {}
    return {
        "budget": as_int(cfg.get("default_budget"), 6000),
        "max_budget": as_int(cfg.get("max_budget"), 12000),
        "chars_per_token": as_int(
            cfg.get("token_chars"), as_int(output.get("token_chars"), 4)
        ),
        "max_paths": as_int(cfg.get("max_paths"), 15),
        "max_tables": as_int(cfg.get("max_tables"), 10),
    }


def _tokens(text: str, chars_per_token: int) -> int:
    return math.ceil(len(text or "") / max(chars_per_token, 1))


def _rows(conn, sql: str, args=()):
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def _git_changed(repo: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line[3:].strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def _anchor(conn, ctx, params):
    if params.get("path"):
        value = str(params["path"]).replace("\\", "/")
        rows = _rows(conn, "SELECT * FROM files WHERE path=? OR path LIKE ?", (value, value + "/%"))
        return {"type": "path", "value": value, "resolved": [row["path"] for row in rows]}, rows
    if params.get("table"):
        value = str(params["table"])
        exists = _rows(conn, "SELECT name FROM tables WHERE name=?", (value,))
        ops = _rows(conn, "SELECT * FROM table_ops WHERE table_name=?", (value,))
        return {"type": "table", "value": value, "resolved": [value] if exists else []}, ops
    if params.get("symbol"):
        value = str(params["symbol"])
        rows = _rows(conn, "SELECT * FROM symbols WHERE name LIKE ?", (f"%{value}%",))
        return {"type": "symbol", "value": value, "resolved": [row["name"] for row in rows]}, rows
    if params.get("dir"):
        value = str(params["dir"]).replace("\\", "/").rstrip("/")
        rows = _rows(conn, "SELECT * FROM files WHERE path LIKE ?", (value + "/%",))
        return {"type": "dir", "value": value, "resolved": [row["path"] for row in rows]}, rows
    if as_bool(params.get("changed")):
        paths = _git_changed(legacy_repo(ctx))
        rows = []
        for path in paths:
            rows.extend(_rows(conn, "SELECT * FROM files WHERE path=?", (path,)))
        return {"type": "changed", "value": f"{len(paths)} arquivo(s)", "resolved": paths}, rows
    return None, []


def _file_entry(row, reason, score):
    loc = int(row.get("loc") or 0)
    return {
        "path": row.get("path"),
        "line_start": 1,
        "line_end": max(loc, 1),
        "reason": reason,
        "score": score,
        "surface": row.get("surface") or "",
    }


# Trechos adicionais por arquivo (``also``) exibidos no brief; o excedente vira contagem.
ALSO_MAX = 10


def _finish_also(item: dict) -> None:
    """Normaliza ``also``: sem repetidos, sem o trecho principal, escritas primeiro."""
    main = (item["line_start"], item["line_end"])
    seen = set()
    spans = []
    for span in item.pop("also", None) or []:
        key = (span["line_start"], span["line_end"], span["reason"])
        if key in seen or (key[0], key[1]) == main:
            continue
        seen.add(key)
        spans.append(span)
    spans.sort(key=lambda span: (not span["reason"].startswith("escreve"), span["line_start"]))
    if spans:
        item["also"] = spans[:ALSO_MAX]
        if len(spans) > ALSO_MAX:
            item["also_omitted"] = len(spans) - ALSO_MAX


def _read_first(conn, anchor, rows, max_paths):
    candidates: dict[str, dict] = {}

    def add(path, reason, score, line_start=1, line_end=None, merge=False):
        """Mantém uma entrada por arquivo (a de maior prioridade).

        Com ``merge``, os demais trechos do mesmo arquivo (ex.: leituras de um
        arquivo que também escreve na tabela) ficam em ``also`` em vez de sumir.
        """
        if not path:
            return
        entry = {
            "path": path,
            "line_start": line_start,
            "line_end": line_end or 1,
            "reason": reason,
            "score": score,
            "also": [],
        }
        current = candidates.get(path)
        if current is None:
            candidates[path] = entry
            return
        if score > current["score"]:
            entry["also"] = current["also"]
            winner, loser = entry, current
            candidates[path] = entry
        else:
            winner, loser = current, entry
        if merge:
            winner["also"].append(
                {
                    "line_start": loser["line_start"],
                    "line_end": loser["line_end"],
                    "reason": loser["reason"],
                }
            )

    kind = anchor["type"]
    if kind == "path":
        for row in rows:
            add(row["path"], "âncora (arquivo selecionado)", 100, 1, max(int(row.get("loc") or 1), 1))
        for row in rows:
            base = os.path.basename(row["path"])
            for imp in _rows(conn, "SELECT * FROM imports WHERE target_path LIKE ?", (f"%{base}%",)):
                add(imp["file_path"], f"importa {base}", 40)
            for inc in _rows(conn, "SELECT * FROM includes WHERE target_path LIKE ?", (f"%{base}%",)):
                add(inc["file_path"], f"inclui {base}", 40)
            for op in _rows(conn, "SELECT * FROM table_ops WHERE file_path=?", (row["path"],)):
                add(row["path"], f"opera em {op['table_name']}", 60, op["line"], op["line"])
        surfaces = {row.get("surface") for row in rows if row.get("surface")}
        for surface in surfaces:
            for item in _rows(conn, "SELECT * FROM files WHERE surface=?", (surface,))[:5]:
                add(item["path"], f"mesma superfície ({surface})", 20)
    elif kind == "table":
        writes = [op for op in rows if op.get("access") == "write"]
        reads = [op for op in rows if op.get("access") != "write"]
        for op in writes:
            add(op["file_path"], f"escreve em {op['table_name']}", 90, op["line"], op["line"], merge=True)
        for op in reads:
            add(op["file_path"], f"lê {op['table_name']}", 70, op["line"], op["line"], merge=True)
        for fk in _rows(conn, "SELECT * FROM fk_inferred WHERE from_table=? OR to_table=?", (anchor["value"], anchor["value"])):
            other = fk["to_table"] if fk["from_table"] == anchor["value"] else fk["from_table"]
            for op in _rows(conn, "SELECT * FROM table_ops WHERE table_name=?", (other,))[:3]:
                add(op["file_path"], f"tabela relacionada {other}", 40, op["line"], op["line"])
    elif kind == "symbol":
        for row in rows:
            add(row["file_path"], f"define {row['name']}", 95, row["line_start"], row["line_start"])
            for op in _rows(conn, "SELECT * FROM table_ops WHERE symbol=?", (row["name"],)):
                add(op["file_path"], f"{row['name']} opera em {op['table_name']}", 80, op["line"], op["line"])
    elif kind == "dir":
        for row in rows:
            add(row["path"], "arquivo do diretório", 50, 1, max(int(row.get("loc") or 1), 1))
    elif kind == "changed":
        for path in anchor["resolved"]:
            add(path, "arquivo alterado", 85)

    ordered = sorted(candidates.values(), key=lambda item: (-item["score"], item["path"]))
    omitted = max(len(ordered) - max_paths, 0)
    for item in ordered:
        item.pop("score", None)
        _finish_also(item)
    return ordered[:max_paths], omitted


def _impact(conn, anchor, max_tables):
    tables = []
    if anchor["type"] == "table":
        rows = _rows(conn, "SELECT * FROM table_ops WHERE table_name=?", (anchor["value"],))
        fks = _rows(conn, "SELECT * FROM fk_inferred WHERE from_table=? OR to_table=?", (anchor["value"], anchor["value"]))
        tables = [{
            "name": anchor["value"],
            "writes": sum(1 for row in rows if row.get("access") == "write"),
            "reads": sum(1 for row in rows if row.get("access") != "write"),
            "fks": len(fks),
        }]
    elif anchor["type"] == "path":
        names = {row["table_name"] for row in _rows(conn, "SELECT * FROM table_ops WHERE file_path IN (%s)" % ",".join("?" * max(len(anchor["resolved"]), 1)), tuple(anchor["resolved"] or [""]))}
        for name in sorted(names)[:max_tables]:
            rows = _rows(conn, "SELECT * FROM table_ops WHERE table_name=?", (name,))
            tables.append({
                "name": name,
                "writes": sum(1 for row in rows if row.get("access") == "write"),
                "reads": sum(1 for row in rows if row.get("access") != "write"),
                "fks": len(_rows(conn, "SELECT * FROM fk_inferred WHERE from_table=? OR to_table=?", (name, name))),
            })
    elif anchor["type"] == "symbol":
        names = set()
        for row in _rows(conn, "SELECT DISTINCT table_name FROM table_ops WHERE symbol LIKE ?", (f"%{anchor['value']}%",)):
            names.add(row["table_name"])
        for name in sorted(names)[:max_tables]:
            rows = _rows(conn, "SELECT * FROM table_ops WHERE table_name=?", (name,))
            tables.append({"name": name, "writes": sum(1 for row in rows if row.get("access") == "write"), "reads": sum(1 for row in rows if row.get("access") != "write"), "fks": 0})
    return tables


def _also_text(item: dict) -> str:
    """Resumo dos demais trechos do arquivo: `` (+ lê tabela: L637, L650)``."""
    groups: dict[str, list[str]] = {}
    for span in item.get("also") or []:
        start, end = span["line_start"], span["line_end"]
        label = f"L{start}" if start == end else f"L{start}-{end}"
        groups.setdefault(span["reason"], []).append(label)
    if not groups:
        return ""
    parts = [f"{reason}: {', '.join(labels)}" for reason, labels in groups.items()]
    omitted = int(item.get("also_omitted") or 0)
    if omitted:
        parts.append(f"+{omitted} omitido(s)")
    return f" (+ {'; '.join(parts)})"


def _render(packet: dict) -> str:
    anchor = packet["anchor"]
    freshness = packet["freshness"]
    lines = [
        f"# Brief: {anchor['type']} `{anchor['value']}`",
        "",
        f"- modo: {packet['mode']}",
        f"- frescor: {freshness.get('status')} (commit {str(freshness.get('commit') or '-')[:8]})",
        f"- orçamento: ~{packet['budget']['estimated']}/{packet['budget']['requested']} tok"
        + (" (truncado)" if packet["budget"]["truncated"] else ""),
        "",
        "## Ler primeiro",
        "",
    ]
    if packet["read_first"]:
        for item in packet["read_first"]:
            lines.append(
                f"- `{item['path']}:{item['line_start']}-{item['line_end']}` — "
                f"{item['reason']}{_also_text(item)}"
            )
    else:
        lines.append("- (nada resolvido; rode `code:skeleton`/`db:links`)")
    lines += ["", "## Impacto", ""]
    if packet["impact"]["tables"]:
        for table in packet["impact"]["tables"]:
            lines.append(
                f"- `{table['name']}` — {table['writes']} escrita(s), "
                f"{table['reads']} leitura(s), {table['fks']} FK(s)"
            )
    else:
        lines.append("- (nenhuma tabela relacionada)")
    if packet["validation"]:
        lines += ["", "## Validação", ""]
        lines += [f"- pipeline `{name}`" for name in packet["validation"]]
    if packet["findings"]:
        lines += ["", "## Achados", ""]
        lines += [f"- {item}" for item in packet["findings"]]
    if packet["omissions"]:
        lines += ["", "## Omissões", ""]
        for item in packet["omissions"]:
            lines.append(f"- {item['section']}: {item['count']} omitido(s) — `{item['next_command']}`")
    lines += ["", "> Orientação apenas. Confirme no código antes de editar."]
    return "\n".join(lines)


def build(ctx, params) -> dict:
    settings = _settings(ctx)
    budget = min(
        max(as_int(params.get("budget"), settings["budget"]), 500),
        settings["max_budget"],
    )
    max_paths = max(as_int(params.get("max_paths"), settings["max_paths"]), 1)
    max_tables = max(as_int(params.get("max_tables"), settings["max_tables"]), 1)
    mode = str(params.get("mode") or "implementation")

    conn = graphdb.connect(ctx)
    try:
        anchor, rows = _anchor(conn, ctx, params)
        if anchor is None:
            return {
                "error": "informe path, table, symbol, dir ou changed",
                "hint": "Ex.: `code:brief --table tb_alugueis`",
            }
        read_first, omitted_paths = _read_first(conn, anchor, rows, max_paths)
        tables = _impact(conn, anchor, max_tables)
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("files", "symbols", "tables", "table_ops")
        }
    finally:
        conn.close()

    fresh = manifest.verify(ctx)
    findings = []
    if not anchor["resolved"]:
        findings.append("âncora não encontrada no store; rode `code:skeleton`/`db:links`")
    if not counts["files"]:
        findings.append("store vazio; rode `code:skeleton` e `db:links`")
    if fresh["status"] != "fresh":
        findings.append(f"frescor {fresh['status']}: {'; '.join(fresh.get('reasons') or [])}")

    omissions = []
    if omitted_paths:
        omissions.append({
            "section": "read_first",
            "count": omitted_paths,
            "next_command": f"code:brief --{anchor['type']} {anchor['value']} --max_paths {max_paths + omitted_paths}",
        })

    validation = sorted((ctx.config.get("pipelines") or {}).keys())
    packet = {
        "schema": "harness.brief.v1",
        "mode": mode,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "freshness": {
            "status": fresh.get("status"),
            "commit": (fresh.get("repo") or {}).get("commit"),
            "dirty": (fresh.get("repo") or {}).get("dirty"),
            "reasons": fresh.get("reasons") or [],
        },
        "anchor": anchor,
        "budget": {"requested": budget, "estimated": 0, "truncated": False},
        "read_first": read_first,
        "impact": {"tables": tables, "counts": counts},
        "validation": validation,
        "findings": findings,
        "omissions": omissions,
        "instructions": {
            "source_read_required": True,
            "summary": "Orientação apenas. Confirme no código antes de editar.",
        },
    }

    # Ajusta o pacote ao orçamento, descartando os itens de menor prioridade.
    while read_first:
        packet["budget"]["estimated"] = _tokens(
            redact_packet(packet, ctx), settings["chars_per_token"]
        )
        if packet["budget"]["estimated"] <= budget:
            break
        read_first.pop()
        packet["budget"]["truncated"] = True
        packet["omissions"].append(
            {
                "section": "read_first",
                "count": 1,
                "next_command": f"code:brief --{anchor['type']} {anchor['value']} --budget {budget * 2}",
            }
        )
    packet["budget"]["estimated"] = _tokens(redact_packet(packet, ctx), settings["chars_per_token"])
    return packet


def redact_packet(packet: dict, ctx) -> str:
    text = _render(packet)
    policy = redact.get_policy(ctx.config)
    text, _stats = redact.redact_text(text, policy)
    return text


def render(packet: dict) -> str:
    return _render(packet)


def detect_anchor(ctx, question: str) -> dict | None:
    """Heurística para o `ask` delegar ao brief quando a pergunta cita uma âncora."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", question or "")
    if not tokens:
        return None
    conn = graphdb.connect(ctx)
    try:
        for token in sorted(set(tokens), key=len, reverse=True):
            if conn.execute("SELECT 1 FROM tables WHERE name=?", (token,)).fetchone():
                return {"table": token}
            if conn.execute("SELECT 1 FROM symbols WHERE name LIKE ?", (f"%{token}%",)).fetchone():
                return {"symbol": token}
        for token in tokens:
            if conn.execute("SELECT 1 FROM files WHERE path LIKE ?", (f"%{token}%",)).fetchone():
                return {"path": token}
    finally:
        conn.close()
    return None
