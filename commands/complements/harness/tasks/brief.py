"""Tarefa code:brief — pacote de contexto ancorado (M2)."""

import json

from .. import briefing
from commands.complements.harness_core.catalog import register
from commands.complements.harness_core.task_types import TaskResult, TaskSpec
from commands.complements.harness_core.util import as_bool
from commands.complements.harness_core import redact


def handle(ctx, params):
    packet = briefing.build(ctx, params)
    if packet.get("error"):
        return TaskResult(
            False,
            packet["error"],
            details=packet.get("hint") or "",
            exit_code=2,
        )

    if as_bool(params.get("json")):
        text = json.dumps(packet, ensure_ascii=False, indent=2)
    else:
        text = briefing.render(packet)

    policy = redact.get_policy(ctx.config)
    text, stats = redact.redact_text(text, policy)
    if stats:
        text += f"\n\n[redact: {redact.format_stats(stats)}]\n"

    anchor = packet["anchor"]
    return TaskResult(
        True,
        f"brief: {anchor['type']} {anchor['value']} "
        f"({packet['budget']['estimated']} tok)",
        details=text,
        meta={
            "tokens": int(packet["budget"]["estimated"]),
            "omissions": len(packet.get("omissions") or []),
            "truncated": bool(packet["budget"]["truncated"]),
        },
    )


register(
    TaskSpec(
        name="code:brief",
        pack="harness",
        intent="read",
        description="Pacote limitado de contexto para um path, tabela, símbolo ou diretório",
        required=[],
        optional=[
            "path",
            "table",
            "symbol",
            "dir",
            "changed",
            "mode",
            "budget",
            "max_paths",
            "max_tables",
            "json",
        ],
        handler=handle,
    )
)
