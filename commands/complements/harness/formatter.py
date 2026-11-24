"""Formatação do bloco de resultado, truncamento e mascaramento de segredos."""

import json
import os
import re

from .config import get_legacy

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text or "")


def collapse_repeats(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and lines[j] == lines[i]:
            j += 1
        count = j - i
        if count >= 3:
            out.append(lines[i])
            out.append(f"... ({count - 1} linha(s) repetida(s) omitida(s)) ...")
        else:
            out.extend(lines[i:j])
        i = j
    return "\n".join(out)


DEFAULT_HINT = "Refine a consulta (parâmetros da tarefa) para ver o restante."


def truncation_marker(
    omitted: int,
    hint: str = "",
    detail: str = "",
    unit: str = "linha(s)",
    feminine: bool = True,
) -> str:
    """Marcador padrão de truncamento, sempre no formato ``[truncado: ...]``.

    Diz quanto foi omitido, o que não foi exibido (``detail``) e como pedir o
    resto (``hint``), para que o LLM nunca suponha que o conteúdo acaba ali.
    """
    adjective = "omitida(s)" if feminine else "omitido(s)"
    text = f"[truncado: {omitted} {unit} {adjective}"
    if detail:
        text += f" — {detail}"
    text += f". {hint or DEFAULT_HINT}]"
    return text


def _take_head(lines: list[str], budget: int) -> list[str]:
    kept: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + 1
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    return kept


def _take_tail(lines: list[str], budget: int) -> list[str]:
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        cost = len(line) + 1
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    return kept


def cut_head(
    text: str,
    max_chars: int,
    hint: str = "",
    detail: str = "",
) -> tuple[str, int]:
    """Mantém o início do texto em fronteira de linha e acrescenta o marcador.

    Devolve ``(texto, linhas_omitidas)``; sem corte, ``(texto, 0)``.
    """
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text, 0

    lines = text.split("\n")
    budget = max(max_chars - 240, max_chars // 2)
    kept = _take_head(lines, budget)
    if not kept:
        # Uma única linha maior que o orçamento: corte duro, avisando.
        marker = truncation_marker(
            len(text) - budget,
            hint,
            detail or "linha longa cortada",
            unit="caractere(s)",
            feminine=False,
        )
        return text[:budget] + "\n" + marker, 0

    omitted = len(lines) - len(kept)
    return "\n".join(kept) + "\n" + truncation_marker(omitted, hint, detail), omitted


def truncate(text: str, max_chars: int, hint: str = "") -> tuple[str, bool]:
    """Limita ``text`` a ~``max_chars`` mantendo início e fim, sem cortar linhas.

    O meio é substituído pelo marcador ``[truncado: ...]``. Só uma linha maior
    que o orçamento é cortada no meio (e o marcador informa isso).
    """
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text, False

    text = collapse_repeats(text)
    if len(text) <= max_chars:
        return text, False

    head_budget = max(int(max_chars * 0.6), 1)
    tail_budget = max(int(max_chars * 0.3), 1)

    lines = text.split("\n")
    head = _take_head(lines, head_budget)
    if not head:
        omitted = max(len(text) - head_budget - tail_budget, 0)
        marker = truncation_marker(
            omitted,
            hint,
            "linha longa cortada no meio",
            unit="caractere(s)",
            feminine=False,
        )
        return text[:head_budget] + "\n" + marker + "\n" + text[-tail_budget:], True

    tail = _take_tail(lines[len(head) :], tail_budget)
    omitted = len(lines) - len(head) - len(tail)
    marker = truncation_marker(omitted, hint)
    parts = head + [marker] + tail
    return "\n".join(parts), True


def mask_secrets(text: str, config: dict) -> str:
    if not text:
        return text

    names = []
    for key in ("db_user_env", "db_password_env"):
        value = get_legacy(config, key)
        if value:
            names.append(value)

    for name in names:
        secret = os.environ.get(name)
        if secret and len(secret) >= 3:
            text = text.replace(secret, "***")
    return text


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
    details_text, truncated = truncate(strip_ansi(details or ""), max_chars, hint)

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
