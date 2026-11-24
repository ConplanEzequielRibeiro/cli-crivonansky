"""ask: contexto de notas, orçamento por prioridade e rodapé de uso (T18/T19)."""

from commands.complements.harness import asking, notes


def _note(folder, modulo, tags, tabelas, arquivos, revisado=True):
    meta = {"modulo": modulo, "tags": tags, "tabelas": tabelas, "arquivos": arquivos,
            "hash_fonte": "x", "revisado": revisado, "atualizado_em": "2026-01-01"}
    (folder / f"{modulo}.md").write_text(
        notes.render_note(meta, "# T\n\n" + notes.skeleton_body()), encoding="utf-8"
    )


def test_select_notes_by_tag_table_file_and_module(tmp_path):
    _note(tmp_path, "cadastro", ["veiculo"], ["tb_veiculos"], ["cadastro/veiculo.php"])
    _note(tmp_path, "financeiro", ["boleto"], ["tb_boletos"], ["fin/boleto.php"])

    by_tag = asking.select_notes(str(tmp_path), "como funciona o veiculo?")
    by_table = asking.select_notes(str(tmp_path), "consulta em tb_boletos lenta")
    by_file = asking.select_notes(str(tmp_path), "erro em veiculo.php linha 10")

    assert [n for n, *_ in by_tag] == ["cadastro.md"]
    assert [n for n, *_ in by_table] == ["financeiro.md"]
    assert [n for n, *_ in by_file] == ["cadastro.md"]
    assert asking.select_notes(str(tmp_path), "assunto sem relação") == []


def test_select_notes_ignores_model_and_invalid_files(tmp_path):
    (tmp_path / "_modelo.md").write_text(notes.model_text(), encoding="utf-8")
    (tmp_path / "solta.md").write_text("sem frontmatter veiculo", encoding="utf-8")

    assert asking.select_notes(str(tmp_path), "veiculo") == []


def test_budget_never_exceeded_and_reports_usage():
    sections = [
        ("db", "Banco", "\n".join(f"tabela_{i} coluna_a, coluna_b, coluna_c" for i in range(400))),
        ("map", "Mapa", "\n".join(f"- `arq{i}.php` {i}L" for i in range(200))),
        ("notes", "Fichas", "regra de negócio importante\n" * 10),
    ]

    prompt, usage = asking.fit_sections("pergunta?", sections, 500)

    assert len(prompt) <= 500 * asking.DEFAULT_CHARS_PER_TOKEN
    assert "## Uso do orçamento" in prompt
    assert "[truncado:" in prompt
    assert any(line.startswith("notes:") and "truncado" not in line for line in usage)


def test_priority_drops_low_priority_first():
    sections = [
        ("rag", "RAG", "x " * 3000),
        ("notes", "Fichas", "nota\n" * 40),
    ]

    prompt, usage = asking.fit_sections("p?", sections, 150)

    assert "## Fichas" in prompt
    assert "rag: omitido" in "\n".join(usage)
    assert "## RAG" not in prompt


def test_duplicates_between_contexts_are_removed():
    repeated = "cadastro/veiculo.php salva o veículo na tabela tb_veiculos"
    sections = [("notes", "Fichas", repeated), ("map", "Mapa", repeated + "\noutra linha qualquer")]

    prompt, _ = asking.fit_sections("p?", sections, None)

    assert prompt.count(repeated) == 1


def test_no_budget_keeps_everything():
    prompt, usage = asking.fit_sections("p?", [("map", "Mapa", "a\nb")], None)

    assert "## Mapa" in prompt and "truncado" not in prompt
    assert usage
