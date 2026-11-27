"""Manifesto leve do pack harness; não importa handlers no topo."""

NAME = "harness"
COMMAND = "harness"
DESCRIPTION = "Mapeamento: código, banco, documentação/RAG e contexto"

TASKS = ['code:skeleton', 'code:search', 'code:read', 'code:outline', 'code:symbol', 'db:snapshot', 'db:schema', 'db:query', 'db:links', 'docs:import', 'rag:serve', 'rag:sync', 'rag:search', 'context:pack', 'file:read']
SHORTCUTS = {}
DEFAULT_LLM_DENIED = []


def load_tasks():
    """Importa os handlers deste pack (lazy)."""
    from .tasks import db, docs, env, file, jit, links, prompt, rag, rag_serve, skeleton  # noqa: F401
