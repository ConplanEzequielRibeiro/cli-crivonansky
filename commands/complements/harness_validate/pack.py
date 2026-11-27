"""Manifesto leve do pack harness_validate; não importa handlers no topo."""

NAME = "harness_validate"
COMMAND = "harness-validate"
DESCRIPTION = "Validação: pipelines test:run, verify e lint"

TASKS = ['test:run', 'verify', 'lint']
SHORTCUTS = {}
DEFAULT_LLM_DENIED = []


def load_tasks():
    """Importa os handlers deste pack (lazy)."""
    from .tasks import pipelines  # noqa: F401
