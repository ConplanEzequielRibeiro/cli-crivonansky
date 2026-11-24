"""Política de aprovação e bloqueio de comandos perigosos."""

import json
import re

# Tarefas que um bloco vindo do LLM nunca executa: só o usuário, digitando.
DEFAULT_LLM_DENIED = (
    "shell:run",
    "py:run",
    "docker:exec",
    "watch:clip",
    "watch:downloads",
)


def llm_task_denied(policy: dict, task: str) -> str | None:
    """Motivo da negação de ``task`` para blocos do LLM (ou ``None``).

    ``policy.llm_allowed_tasks``, quando definido, vence: só ele é permitido.
    Sem ele, vale ``policy.llm_denied_tasks`` (padrão: shell, python e docker).
    """
    allowed = policy.get("llm_allowed_tasks")
    if allowed is not None:
        if task not in {str(item) for item in allowed}:
            return f"tarefa {task} não está em policy.llm_allowed_tasks"
        return None

    denied = policy.get("llm_denied_tasks")
    denied = DEFAULT_LLM_DENIED if denied is None else tuple(str(item) for item in denied)
    if task in denied:
        return (
            f"tarefa {task} só pode ser executada pela linha de comando "
            f"(`harness run {task}`), não por bloco do LLM"
        )
    return None


def check_policy(
    block,
    spec,
    config: dict,
    interactive: bool,
    yes_allowed: bool,
    yes: bool,
    origin: str | None = None,
) -> tuple[str, str]:
    """Devolve (decisão, motivo), com decisão em allow | deny | confirm.

    ``origin`` é ``"user"`` ou ``"llm"``; sem ele, deduz-se de ``yes_allowed``
    (blocos que aceitam ``--yes`` são os digitados pelo usuário).
    """

    policy = config.get("policy") or {}
    payload = json.dumps(block.params, ensure_ascii=False, default=str)
    origin = origin or ("user" if yes_allowed else "llm")

    if origin == "llm":
        reason = llm_task_denied(policy, block.task)
        if reason:
            return "deny", reason

    for pattern in policy.get("deny_patterns") or []:
        try:
            if re.search(pattern, payload):
                return "deny", f"padrão proibido: {pattern}"
        except re.error:
            continue

    intent = spec.intent
    if spec.intent_fn is not None:
        intent = spec.intent_fn(block.params)
    # O bloco pode elevar para escrita, mas nunca rebaixar.
    if block.intent == "write":
        intent = "write"

    if intent == "read":
        return "allow", "leitura"

    if yes_allowed and yes:
        return "allow", "--yes"

    if not interactive:
        return "deny", "escrita requer confirmação interativa"

    return "confirm", "escrita requer confirmação"
