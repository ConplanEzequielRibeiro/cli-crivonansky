"""Manifesto leve do pack harness_state; não importa handlers no topo."""

NAME = "harness_state"
COMMAND = "harness-state"
DESCRIPTION = "Estado: continuidade de tarefa entre conversas"

TASKS = ['state:save', 'state:load', 'state:list']
SHORTCUTS = {'save': 'state:save', 'load': 'state:load', 'list': 'state:list'}
DEFAULT_LLM_DENIED = []


def load_tasks():
    """Importa os handlers deste pack (lazy)."""
    from .tasks import state  # noqa: F401
