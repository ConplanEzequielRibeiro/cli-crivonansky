"""Tipos compartilhados do plugin harness."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class TaskResult:
    """Resultado de uma tarefa."""

    success: bool
    summary: str
    details: str = ""
    artifacts: list[str] = field(default_factory=list)
    exit_code: int = 0
    status: str | None = None
    # Dica de continuação exibida no marcador de truncamento (ex.: "use `path`").
    hint: str = ""
    # Métricas opcionais para runs.jsonl (tokens, omissões, classes...).
    meta: dict = field(default_factory=dict)


@dataclass
class TaskContext:
    """Contexto de execução passado a cada tarefa."""

    config: dict
    workspace: str
    run_dir: str
    interactive: bool = True
    yes: bool = False
    dry_run: bool = False
    # Origem do bloco: "user" (linha de comando) ou "llm" (bloco colado do chat).
    origin: str = "user"
    # Dados resolvidos pelo ``preview_fn`` antes da confirmação (ex.: texto da ficha).
    prepared: dict = field(default_factory=dict)


@dataclass
class TaskSpec:
    """Definição de uma tarefa do catálogo."""

    name: str
    intent: str  # "read" | "write"
    description: str
    required: list[str]
    optional: list[str]
    handler: Callable[[TaskContext, dict], TaskResult]
    intent_fn: Callable[[dict], str] | None = None
    # Mostra o que será gravado antes da confirmação y/N (tarefas de escrita).
    preview_fn: Callable[[TaskContext, dict], str | None] | None = None
    # Pack dono da tarefa. "core" fica disponível em todos os comandos.
    pack: str = "harness"
