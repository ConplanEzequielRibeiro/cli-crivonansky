"""Tarefas audit:removal e audit:verify (M3)."""

import json

from .. import audit
from commands.complements.harness_core.catalog import register
from commands.complements.harness_core.task_types import TaskResult, TaskSpec
from commands.complements.harness_core.util import as_bool


def handle_removal(ctx, params):
    target = str(params.get("target") or "").strip()
    if not target:
        return TaskResult(False, "parâmetro 'target' obrigatório", exit_code=2)
    matchers = params.get("matcher") or []
    if isinstance(matchers, str):
        matchers = [item.strip() for item in matchers.split(",") if item.strip()]
    ledger = audit.create(
        ctx,
        target,
        kind=str(params.get("kind") or "removal"),
        matchers=matchers,
        write=params.get("write"),
    )
    text = (
        json.dumps(ledger, ensure_ascii=False, indent=2)
        if as_bool(params.get("json"))
        else audit.describe_ledger(ledger)
    )
    return TaskResult(
        True,
        f"ledger: {ledger['verdict']['status']} ({ledger['target']['raw']})",
        details=text,
        artifacts=[ledger["path"]],
    )


def handle_verify(ctx, params):
    data = audit.verify(
        ctx,
        path=params.get("ledger"),
        fail_on_leftovers=as_bool(params.get("fail_on_leftovers")),
    )
    text = (
        json.dumps(data, ensure_ascii=False, indent=2)
        if as_bool(params.get("json"))
        else audit.describe_verify(data)
    )
    return TaskResult(
        bool(data.get("ok")),
        f"verificação: {data['status']}",
        details=text,
        exit_code=0 if data.get("ok") else 2,
    )


register(
    TaskSpec(
        name="audit:removal",
        pack="harness",
        intent="write",
        description="Cria um ledger de completude para remoção/migração",
        required=["target"],
        optional=["kind", "matcher", "write", "json"],
        handler=handle_removal,
    )
)
register(
    TaskSpec(
        name="audit:verify",
        pack="harness",
        intent="read",
        description="Reexecuta um ledger e falha fechado se sobrarem referências ativas",
        required=[],
        optional=["ledger", "fail_on_leftovers", "json"],
        handler=handle_verify,
    )
)
