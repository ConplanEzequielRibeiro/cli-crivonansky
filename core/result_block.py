"""Bloco ``crivonansky-result`` para comandos do core.

Espelha o envelope de ``harness_core.formatter`` para que comandos fora do
harness (ex.: ``/help``) tenham a mesma saída das tarefas: bloco
``crivonansky-result`` impresso e copiado para o clipboard. Não importa o
harness de propósito — o CLI precisa funcionar sem PyYAML/sqlglot instalados.
"""

import json
import uuid

# Mesmo limite usado pelo harness para o texto que vai ao clipboard.
MAX_CHARS = 12000
DEFAULT_HINT = "use `/<comando> --help` para o detalhe"


def new_id() -> str:
    return f"c-{uuid.uuid4().hex[:8]}"


def truncate(text: str, max_chars: int, hint: str = "") -> tuple[str, bool]:
    """Corta o texto no orçamento e marca o que ficou de fora."""
    if len(text or "") <= max_chars:
        return text or "", False
    keep = max(max_chars - 160, 0)
    omitted = len(text) - keep
    marker = f"[truncado: {omitted} caractere(s) omitido(s). {hint or DEFAULT_HINT}]"
    return text[:keep].rstrip() + "\n" + marker, True


def format_result(
    block_id: str,
    task: str,
    status: str,
    exit_code: int,
    duration_ms: int,
    summary: str,
    details: str,
    artifacts: list[str],
    max_chars: int,
    hint: str = "",
) -> tuple[str, bool]:
    details_text, truncated = truncate(details or "", max_chars, hint)

    lines = [
        "```crivonansky-result",
        "harness: 1",
        f"id: {block_id}",
        f"task: {task}",
        f"status: {status}",
        f"exit_code: {exit_code}",
        f"duration_ms: {duration_ms}",
        f"summary: {json.dumps(summary, ensure_ascii=False)}",
        f"truncated: {'true' if truncated else 'false'}",
    ]
    if artifacts:
        lines.append("artifacts:")
        for artifact in artifacts:
            lines.append(f"  - {artifact}")
    if details_text:
        lines.append("details: |")
        for line in details_text.splitlines():
            lines.append(f"  {line}")
    lines.append("```")

    return "\n".join(lines), truncated


def copy_to_clipboard(text: str) -> bool:
    """Copia o bloco; sem pyperclip (ou sem clipboard) apenas ignora."""
    try:
        import pyperclip

        pyperclip.copy(text)
        return True
    except Exception:  # noqa: BLE001 - clipboard é best-effort
        return False
