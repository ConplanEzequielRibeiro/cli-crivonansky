"""ask: orçamento por prioridade, rodapé de uso e ausência de notas (R0.5)."""

from commands.complements.harness import asking


def test_default_context_has_no_notes():
    assert asking.DEFAULT_CONTEXT == "map,db"
    assert "notes" not in asking.PRIORITY


def test_budget_never_exceeded_and_reports_usage():
    sections = [
        ("db", "Banco", "\n".join(f"tabela_{i} coluna_a, coluna_b, coluna_c" for i in range(400))),
        ("map", "Mapa", "\n".join(f"- `arq{i}.php` {i}L" for i in range(5))),
        ("code", "Código", "linha de código relevante\n" * 10),
    ]

    prompt, usage = asking.fit_sections("pergunta?", sections, 500)

    assert len(prompt) <= 500 * asking.DEFAULT_CHARS_PER_TOKEN
    assert "## Uso do orçamento" in prompt
    assert "[truncado:" in prompt
    assert any(line.startswith("map:") and "truncado" not in line for line in usage)


def test_priority_drops_low_priority_first():
    sections = [
        ("rag", "RAG", "x " * 3000),
        ("map", "Mapa", "mapa\n" * 40),
    ]

    prompt, usage = asking.fit_sections("p?", sections, 150)

    assert "## Mapa" in prompt
    assert "rag: omitido" in "\n".join(usage)
    assert "## RAG" not in prompt


def test_duplicates_between_contexts_are_removed():
    repeated = "cadastro/veiculo.php salva o veículo na tabela tb_veiculos"
    sections = [("map", "Mapa", repeated), ("db", "Banco", repeated + "\noutra linha qualquer")]

    prompt, _ = asking.fit_sections("p?", sections, None)

    assert prompt.count(repeated) == 1


def test_no_budget_keeps_everything():
    prompt, usage = asking.fit_sections("p?", [("map", "Mapa", "a\nb")], None)

    assert "## Mapa" in prompt and "truncado" not in prompt
    assert usage
