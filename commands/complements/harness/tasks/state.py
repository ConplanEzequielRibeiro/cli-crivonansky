"""Tarefas state:save, state:load e state:list (T21)."""

import difflib
import os

from .. import state as st
from ..catalog import register
from ..formatter import cut_head
from ..task_types import TaskResult, TaskSpec
from ..util import ensure_dir, is_within, read_text, state_path, workspace

MAP_LIMIT = 6000


def _legacy_state_dir(ctx) -> str | None:
    """Pasta antiga em ``knowledge.notes_path/estado`` (migração única, R0.8)."""
    configured = ((ctx.config or {}).get("knowledge") or {}).get("notes_path")
    if not configured:
        return None
    from ..config import resolve_path

    return os.path.join(resolve_path(ctx.config, str(configured)), st.STATE_DIR)


def _migrate_legacy(ctx, root: str) -> None:
    legacy = _legacy_state_dir(ctx)
    target = os.path.join(root, st.STATE_DIR)
    if not legacy or not os.path.isdir(legacy) or os.path.isdir(target):
        return
    import shutil

    shutil.copytree(legacy, target)


def _root(ctx) -> str:
    root = state_path(ctx)
    _migrate_legacy(ctx, root)
    return root


def _folder(ctx) -> str:
    return os.path.join(_root(ctx), st.STATE_DIR)


def _incoming(ctx, params) -> str:
    if params.get("content"):
        return str(params["content"])
    if params.get("clip"):
        import pyperclip

        return str(pyperclip.paste() or "")
    if params.get("file"):
        from ..util import ensure_allowed

        return read_text(ensure_allowed(ctx, str(params["file"])))
    return ""


def _prepare(ctx, params):
    raw = _incoming(ctx, params)
    if not raw.strip():
        raise st.StateError("nenhum estado informado (use content, file ou clip)")
    state = st.parse_state(raw)
    folder = _folder(ctx)
    path = os.path.abspath(os.path.join(folder, st.state_filename(state)))
    if not is_within(path, [state_path(ctx)]):
        raise st.StateError("destino fora de state.path")
    return path, st.render_state(state)


def preview_save(ctx, params):
    try:
        path, final = _prepare(ctx, params)
    except st.StateError as exc:
        return f"(estado inválido: {exc})"
    ctx.prepared["state"] = (path, final)
    name = os.path.basename(path)
    if not os.path.isfile(path):
        return f"Novo estado: {name}\n{final}"
    diff = difflib.unified_diff(
        read_text(path).replace("\r\n", "\n").splitlines(),
        final.splitlines(),
        fromfile=f"{name} (atual)",
        tofile=f"{name} (novo)",
        lineterm="",
    )
    return "\n".join(diff) or f"{name}: sem mudanças"


def handle_save(ctx, params):
    try:
        path, final = ctx.prepared.get("state") or _prepare(ctx, params)
    except st.StateError as exc:
        return TaskResult(False, f"estado inválido: {exc}", exit_code=2)
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(final)
    return TaskResult(
        True,
        f"estado gravado: {os.path.basename(path)}",
        details=f"caminho: {path}\n(sem commit automático)",
        artifacts=[path],
    )


def _find(ctx, name: str | None):
    names = st.list_states(_root(ctx))
    if not names:
        return None
    if not name or str(name).lower() == "last":
        return names[-1]
    wanted = str(name).lower()
    matches = [n for n in names if wanted in n.lower()]
    return matches[-1] if matches else None


def handle_load(ctx, params):
    name = _find(ctx, params.get("name"))
    if name is None:
        return TaskResult(
            False,
            "nenhum estado encontrado",
            hint="Use `state:list` para ver os estados salvos.",
            exit_code=2,
        )
    path = os.path.join(_folder(ctx), name)
    try:
        state = st.read_state(read_text(path))
    except st.StateError as exc:
        return TaskResult(False, f"estado inválido em {name}: {exc}", exit_code=2)

    map_text = ""
    map_path = os.path.join(workspace(ctx), "knowledge", "skeleton", "MAP.md")
    if os.path.isfile(map_path):
        map_text, _ = cut_head(
            read_text(map_path), MAP_LIMIT, hint="Use `code:skeleton level=dir path=<dir>`."
        )
    return TaskResult(
        True,
        f"prompt de retomada: {state['tarefa']} ({name})",
        details=st.resume_prompt(state, map_text),
    )


def handle_list(ctx, params):
    names = st.list_states(_root(ctx))
    if not names:
        return TaskResult(True, "nenhum estado salvo", details=_folder(ctx))
    return TaskResult(True, f"{len(names)} estado(s)", details="\n".join(f"- {n}" for n in names))


register(TaskSpec(
    name="state:save", intent="write",
    description="Valida e grava um bloco crivonansky-state em state.path/estado/",
    required=[], optional=["content", "file", "clip"],
    handler=handle_save, preview_fn=preview_save,
))
register(TaskSpec(
    name="state:load", intent="read",
    description="Monta o prompt de retomada (estado + mapa) de um estado salvo",
    required=[], optional=["name", "last"], handler=handle_load,
))
register(TaskSpec(
    name="state:list", intent="read",
    description="Lista os estados de tarefa salvos",
    required=[], optional=[], handler=handle_list,
))
