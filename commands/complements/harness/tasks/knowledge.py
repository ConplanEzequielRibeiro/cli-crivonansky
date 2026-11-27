"""Tarefa knowledge:verify — frescor do mapa e dos vínculos (M0)."""

import json

from .. import manifest
from commands.complements.harness_core.catalog import register
from commands.complements.harness_core.task_types import TaskResult, TaskSpec
from commands.complements.harness_core.util import as_bool


def handle(ctx, params):
    data = manifest.verify(
        ctx,
        deep=as_bool(params.get("deep")),
        fail_on_dirty=as_bool(params.get("fail_on_dirty")),
    )
    summary = f"frescor: {data['status']}"
    if as_bool(params.get("json")):
        details = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        details = manifest.describe(data)
    return TaskResult(
        bool(data.get("ok")),
        summary,
        details=details,
        exit_code=0 if data.get("ok") else 2,
    )


register(
    TaskSpec(
        name="knowledge:verify",
        pack="harness",
        intent="read",
        description="Verifica se o mapa/vínculos correspondem ao commit e às fontes atuais",
        required=[],
        optional=["deep", "fail_on_dirty", "json"],
        handler=handle,
    )
)
