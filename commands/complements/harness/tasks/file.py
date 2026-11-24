"""Tarefas file:read e context:pack."""

import os

from .. import redact
from ..catalog import register
from ..formatter import truncation_marker
from ..task_types import TaskResult, TaskSpec
from ..util import as_int, as_list, ensure_allowed, read_text, source_encoding


def handle_read(ctx, params):
    path = params.get("path")
    if not path:
        return TaskResult(False, "parâmetro 'path' obrigatório", exit_code=2)

    try:
        full = ensure_allowed(ctx, str(path))
    except PermissionError as exc:
        return TaskResult(False, str(exc), exit_code=3)

    if not os.path.isfile(full):
        return TaskResult(False, f"arquivo não encontrado: {path}", exit_code=2)

    text = redact.redact_source(read_text(full, source_encoding(ctx)), ctx.config)
    lines = text.splitlines()
    start = max(1, as_int(params.get("start"), 1))
    end = min(len(lines), as_int(params.get("end"), len(lines)))
    numbered = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
    return TaskResult(
        True,
        f"{path}: linhas {start}-{end} de {len(lines)}",
        details=numbered,
    )


def handle_pack(ctx, params):
    files = as_list(params.get("files"))
    if not files:
        return TaskResult(False, "parâmetro 'files' obrigatório", exit_code=2)

    budget = as_int(params.get("budget"), 12000)
    chunks = []
    used = 0

    for item in files:
        try:
            full = ensure_allowed(ctx, str(item))
        except PermissionError as exc:
            chunks.append(f"## {item}\n\n(acesso negado: {exc})")
            continue

        if not os.path.isfile(full):
            chunks.append(f"## {item}\n\n(não encontrado)")
            continue

        content = redact.redact_source(read_text(full, source_encoding(ctx)), ctx.config)
        block = f"## {item}\n\n```\n{content}\n```"

        if used + len(block) > budget:
            remaining = budget - used
            pending = [str(name) for name in files[files.index(item) :]]
            if remaining > 200:
                cut = block[:remaining]
                cut = cut[: cut.rfind("\n")] if "\n" in cut else cut
                omitted = block.count("\n") - cut.count("\n")
                chunks.append(
                    cut
                    + "\n"
                    + truncation_marker(
                        omitted,
                        "Peça `file:read` com `start`/`end` para o restante.",
                        f"arquivo(s) não exibido(s): {', '.join(pending[1:]) or 'nenhum'}",
                    )
                )
                used = budget
            else:
                chunks.append(
                    truncation_marker(
                        len(pending),
                        "Aumente `budget` ou peça menos arquivos por vez.",
                        ", ".join(pending),
                        unit="arquivo(s)",
                        feminine=False,
                    )
                )
            break

        chunks.append(block)
        used += len(block)

    return TaskResult(
        True,
        f"{len(files)} arquivo(s) empacotado(s) em ~{used} caracteres",
        details="\n\n".join(chunks),
        hint="Peça menos arquivos por vez ou use `file:read` com `start`/`end`.",
    )


register(
    TaskSpec(
        name="file:read",
        intent="read",
        description="Lê um arquivo do repositório com números de linha",
        required=["path"],
        optional=["start", "end"],
        handler=handle_read,
    )
)

register(
    TaskSpec(
        name="context:pack",
        intent="read",
        description="Empacota arquivos em Markdown respeitando um orçamento",
        required=["files"],
        optional=["ranges", "budget"],
        handler=handle_pack,
    )
)
