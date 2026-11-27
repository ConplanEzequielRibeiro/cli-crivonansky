"""Montagem do prompt do ``ask``: contextos e orçamento de tokens.

As notas/fichas foram removidas (R0.5). O ``ask`` compõe mapa, esqueleto, banco,
código, docs e RAG; o orçamento é estimado em caracteres/token (padrão 4) e
distribuído por prioridade, com truncamento explícito.
"""

from commands.complements.harness_core.formatter import cut_head

# Do mais para o menos importante no corte.
PRIORITY = ("map", "skeleton", "db", "code", "docs", "rag")
DEFAULT_CONTEXT = "map,db"
DEFAULT_CHARS_PER_TOKEN = 4
MIN_USEFUL_CHARS = 200


def estimate_tokens(text: str, chars_per_token: int = DEFAULT_CHARS_PER_TOKEN) -> int:
    return -(-len(text or "") // max(int(chars_per_token or 1), 1))


def _dedupe(text: str, seen: set[str]) -> str:
    """Remove linhas longas já presentes em contextos de maior prioridade."""
    out = []
    for line in text.split("\n"):
        key = line.strip()
        if len(key) >= 24:
            if key in seen:
                continue
            seen.add(key)
        out.append(line)
    return "\n".join(out)


def fit_sections(
    question: str,
    sections: list[tuple[str, str, str]],
    budget_tokens: int | None,
    chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
) -> tuple[str, list[str]]:
    """Monta o prompt. ``sections`` = ``[(chave, título, texto)]``.

    Sem ``budget_tokens`` apenas concatena. Com orçamento, atende por prioridade
    (``PRIORITY``); a pergunta nunca é cortada. Devolve ``(prompt, linhas_de_uso)``.
    """
    head = f"Pergunta: {question}\n"
    ordered = sorted(
        sections,
        key=lambda s: PRIORITY.index(s[0]) if s[0] in PRIORITY else len(PRIORITY),
    )

    seen: set[str] = set()
    prepared = [(key, title, _dedupe(text, seen)) for key, title, text in ordered]

    limit = None if not budget_tokens else int(budget_tokens) * int(chars_per_token or 1)
    # reserva para o rodapé "Uso do orçamento"
    reserve = 140 + 48 * len(prepared)
    remaining = None if limit is None else max(limit - len(head) - reserve, 0)
    parts = [head]
    usage: list[str] = []

    for key, title, text in prepared:
        block_head = f"\n## {title}\n\n"
        if remaining is None:
            parts.append(block_head + text + "\n")
            usage.append(f"{key}: {estimate_tokens(text, chars_per_token)} tok")
            continue

        room = remaining - len(block_head)
        if room < MIN_USEFUL_CHARS:
            usage.append(f"{key}: omitido (~{estimate_tokens(text, chars_per_token)} tok)")
            continue
        if len(text) <= room:
            shown, cut = text, 0
        else:
            # reserva espaço para o marcador, que o cut_head acrescenta ao final
            shown, cut = cut_head(
                text,
                max(room - 260, 80),
                hint="Aumente `--budget` ou peça a parte com a tarefa indicada.",
            )
        parts.append(block_head + shown + "\n")
        remaining -= len(block_head) + len(shown) + 1
        used = estimate_tokens(shown, chars_per_token)
        usage.append(
            f"{key}: {used} tok" + (" (truncado)" if cut else "")
        )

    prompt = "".join(parts).rstrip("\n") + "\n"
    if limit is not None or usage:
        total = estimate_tokens(prompt, chars_per_token)
        footer = "\n## Uso do orçamento\n\n" + "\n".join(f"- {line}" for line in usage)
        footer += f"\n- total: ~{total} tok" + (f" de {budget_tokens}" if budget_tokens else "") + "\n"
        prompt += footer
    return prompt, usage
