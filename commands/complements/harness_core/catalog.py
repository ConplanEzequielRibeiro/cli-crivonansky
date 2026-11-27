"""Catálogo fechado de tarefas do harness."""

from .task_types import TaskSpec

_TASKS: dict[str, TaskSpec] = {}
_loaded = False


def register(spec: TaskSpec) -> None:
    _TASKS[spec.name] = spec


def get_task(name: str) -> TaskSpec | None:
    return _TASKS.get(name)


def all_tasks() -> list[TaskSpec]:
    return sorted(_TASKS.values(), key=lambda spec: spec.name)


def load_tasks() -> None:
    global _loaded
    if _loaded:
        return

    from .packs import load_tasks as _load_packs

    _load_packs()
    _loaded = True


def load_pack(name: str) -> None:
    """Carrega sob demanda os handlers de um pack específico."""
    from .packs import _module

    _module(name).load_tasks()


def dispatch(name: str, ctx, params: dict | None = None):
    """Executa uma tarefa resolvendo o pack dono sob demanda (usado pelo watch)."""
    spec = get_task(name)
    if spec is None:
        from .packs import owner_of

        owner = owner_of(name)
        if owner and owner != "core":
            load_pack(owner)
        spec = get_task(name)
    if spec is None:
        raise KeyError(f"tarefa desconhecida: {name}")
    return spec.handler(ctx, params or {})
