"""Manifesto leve do pack harness_clean; não importa handlers no topo."""

NAME = "harness_clean"
COMMAND = "harness-clean"
DESCRIPTION = "Limpeza: artefatos regeráveis e execuções antigas"

TASKS = ['clean:artifacts', 'clean:runs']
SHORTCUTS = {'artifacts': 'clean:artifacts', 'runs': 'clean:runs'}
DEFAULT_LLM_DENIED = ['clean:artifacts', 'clean:runs']


def load_tasks():
    """Importa os handlers deste pack (lazy)."""
    from .tasks import clean  # noqa: F401
