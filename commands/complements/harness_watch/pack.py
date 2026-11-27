"""Manifesto leve do pack harness_watch; não importa handlers no topo."""

NAME = "harness_watch"
COMMAND = "harness-watch"
DESCRIPTION = "Monitores: clipboard e pasta de downloads"

TASKS = ['watch:clip', 'watch:downloads']
SHORTCUTS = {'clip': 'watch:clip', 'downloads': 'watch:downloads'}
DEFAULT_LLM_DENIED = ['watch:clip', 'watch:downloads']


def load_tasks():
    """Importa os handlers deste pack (implementado na fase D2)."""
    return None
