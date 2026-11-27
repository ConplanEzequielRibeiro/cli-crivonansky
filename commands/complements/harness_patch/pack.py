"""Manifesto leve do pack harness_patch; não importa handlers no topo."""

NAME = "harness_patch"
COMMAND = "harness-patch"
DESCRIPTION = "Patch: aplicação de diff preservando encoding/CRLF/BOM"

TASKS = ['patch:apply']
SHORTCUTS = {'apply': 'patch:apply'}
DEFAULT_LLM_DENIED = ['patch:apply']


def load_tasks():
    """Importa os handlers deste pack (implementado na fase D2)."""
    return None
