"""Manifesto leve do pack harness_exec; não importa handlers no topo."""

NAME = "harness_exec"
COMMAND = "harness-exec"
DESCRIPTION = "Execução: shell, Python, Docker, git e logs"

TASKS = ['shell:run', 'py:run', 'docker:exec', 'logs:tail', 'git:run']
SHORTCUTS = {}
DEFAULT_LLM_DENIED = ['shell:run', 'py:run', 'docker:exec', 'git:run']


def load_tasks():
    """Importa os handlers deste pack (implementado na fase D2)."""
    return None
