"""Manifesto leve do pack harness; não importa handlers no topo."""

NAME = "harness"
COMMAND = "harness"
DESCRIPTION = "Mapeamento: código, banco, documentação/RAG e contexto"

TASKS = ['code:skeleton', 'code:search', 'code:read', 'code:outline', 'code:symbol', 'db:snapshot', 'db:schema', 'db:query', 'db:links', 'docs:import', 'rag:serve', 'rag:sync', 'rag:search', 'context:pack', 'file:read']
SHORTCUTS = {}
DEFAULT_LLM_DENIED = []


def load_tasks():
    """Ponte D1: as tarefas ainda vivem em ``harness.tasks``; a D2 distribui."""
    from .tasks import (  # noqa: F401
        clean,
        db,
        docker,
        docs,
        env,
        file,
        git,
        jit,
        links,
        patch,
        pipelines,
        prompt,
        rag,
        rag_serve,
        shell,
        skeleton,
        state,
        watch,
    )
