"""Tarefas graph:stats e graph:export (M1.7)."""

import json
import os

from .. import graphdb
from commands.complements.harness_core.catalog import register
from commands.complements.harness_core.task_types import TaskResult, TaskSpec
from commands.complements.harness_core.util import as_bool, workspace

TABLES = ("files", "symbols", "imports", "tables", "table_ops", "fk_inferred", "includes")


def handle_stats(ctx, params):
    data = graphdb.stats(ctx)
    if as_bool(params.get("json")):
        details = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        details = "\n".join(f"- {key}: {value}" for key, value in data.items())
    return TaskResult(
        True,
        f"store: {data['files']} arquivo(s), {data['table_ops']} operação(ões)",
        details=details,
    )


def handle_export(ctx, params):
    fmt = str(params.get("format") or "json").lower()
    if fmt not in ("json", "jsonl"):
        return TaskResult(False, "format inválido (use json ou jsonl)", exit_code=2)
    out = params.get("out") or os.path.join(
        workspace(ctx), "knowledge", f"graph-export.{fmt}"
    )
    conn = graphdb.connect(ctx)
    try:
        data = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
            for table in TABLES
        }
    finally:
        conn.close()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    if fmt == "jsonl":
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            for table, rows in data.items():
                for row in rows:
                    fh.write(json.dumps({"table": table, **row}, ensure_ascii=False) + "\n")
    else:
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return TaskResult(True, f"export: {out}", artifacts=[out])


register(
    TaskSpec(
        name="graph:stats",
        pack="harness",
        intent="read",
        description="Mostra contagens do store SQLite (arquivos, símbolos, operações, FKs)",
        required=[],
        optional=["json"],
        handler=handle_stats,
    )
)
register(
    TaskSpec(
        name="graph:export",
        pack="harness",
        intent="write",
        description="Exporta o store para JSON/JSONL (debug explícito)",
        required=[],
        optional=["format", "out"],
        handler=handle_export,
    )
)
