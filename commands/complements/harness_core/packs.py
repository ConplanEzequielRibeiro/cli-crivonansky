"""Registro leve dos packs do harness.

Lê apenas os manifestos ``pack.py`` (constantes), sem importar handlers. Assim o
comando de mapeamento sabe o dono de qualquer tarefa sem carregar os outros packs.
"""

from importlib import import_module
from typing import Iterable

CORE = "core"
CORE_TASKS = ("env:check", "prompt")

KNOWN_PACKS = (
    "harness",
    "harness_exec",
    "harness_patch",
    "harness_validate",
    "harness_state",
    "harness_watch",
    "harness_clean",
)

_CACHE: dict[str, str] | None = None


def _module(pack: str):
    package = __package__ or "commands.complements.harness"
    root = package.rsplit(".", 1)[0] if "." in package else "commands.complements"
    return import_module(f"{root}.{pack}.pack")


def manifests() -> dict[str, object]:
    """Manifestos por pack (import leve, sem handlers)."""
    return {name: _module(name) for name in KNOWN_PACKS}


def build_owner(items: Iterable[tuple[str, Iterable[str]]]) -> dict[str, str]:
    """Constrói ``tarefa -> pack``; nome duplicado é erro fatal."""
    owner: dict[str, str] = {}
    for pack, tasks in items:
        for task in tasks:
            if task in owner:
                raise ValueError(
                    f"tarefa duplicada: {task} em {owner[task]} e {pack}"
                )
            owner[task] = pack
    return owner


def owner_map(refresh: bool = False) -> dict[str, str]:
    """Mapa completo ``tarefa -> pack`` (inclui as tarefas de core)."""
    global _CACHE
    if _CACHE is None or refresh:
        items = [(name, manifest.TASKS) for name, manifest in manifests().items()]
        items.append((CORE, CORE_TASKS))
        _CACHE = build_owner(items)
    return dict(_CACHE)


def owner_of(task: str) -> str | None:
    return owner_map().get(task)


def pack_tasks(pack: str) -> list[str]:
    if pack == CORE:
        return list(CORE_TASKS)
    return list(manifests()[pack].TASKS)


def pack_command(pack: str) -> str | None:
    if pack == CORE:
        return None
    return str(manifests()[pack].COMMAND)


def load_tasks() -> None:
    """Carrega os handlers de todos os packs conhecidos (cada um é lazy)."""
    for name in KNOWN_PACKS:
        _module(name).load_tasks()
