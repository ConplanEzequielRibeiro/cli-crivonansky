"""Testes do esqueleto do código (code:skeleton)."""

import json

from commands.complements.harness.tasks import skeleton
from commands.complements.harness_core.task_types import TaskContext


def _context(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cadastro").mkdir(parents=True)
    (repo / "vendor").mkdir()
    (repo / "cadastro" / "cliente.php").write_text(
        "<?php\n"
        "function salvar_cliente($dados) {\n"
        '    $sql = "INSERT INTO tb_clientes (nome) VALUES (\'x\')";\n'
        "    return $sql;\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "app.js").write_text(
        "function carregar() {\n"
        '  return fetch("/api/clientes?filtro=tb_clientes");\n'
        "}\n",
        encoding="utf-8",
    )
    (repo / "tool.py").write_text(
        "def somar(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (repo / "app.min.js").write_text("var a=1;\n", encoding="utf-8")
    (repo / "vendor" / "lib.php").write_text("<?php function de_vendor() {}\n", encoding="utf-8")

    return TaskContext(
        config={"legacy": {"repo_path": str(repo)}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def test_skeleton_indexes_sources_and_skips_vendor(tmp_path):
    ctx = _context(tmp_path)

    result = skeleton.handle(ctx, {})

    assert result.success
    data = json.loads(
        (tmp_path / "ws" / "knowledge" / "skeleton" / "project.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(data["files_index"]) == {
        "cadastro/cliente.php",
        "app.js",
        "tool.py",
    }
    assert data["tables"] == {"tb_clientes": ["cadastro/cliente.php"]}

    entry = data["files_index"]["cadastro/cliente.php"]
    assert entry["symbols"][0]["name"] == "salvar_cliente"
    assert entry["symbols"][0]["line"] == 2
    assert entry["symbols"][0]["end"] >= 4


def test_skeleton_markdown_has_tables_and_symbols(tmp_path):
    ctx = _context(tmp_path)

    skeleton.handle(ctx, {})

    text = (tmp_path / "ws" / "knowledge" / "skeleton" / "SKELETON.md").read_text(
        encoding="utf-8"
    )
    assert "## Tabelas" in text
    assert "`tb_clientes`" in text
    assert "`salvar_cliente` (L2)" in text
    assert "## Como navegar" in text


def test_skeleton_is_incremental(tmp_path):
    ctx = _context(tmp_path)
    skeleton.handle(ctx, {})

    result = skeleton.handle(ctx, {})

    assert result.success
    assert "reaproveitado(s)" in result.summary


def test_skeleton_full_reparses_everything(tmp_path):
    ctx = _context(tmp_path)
    skeleton.handle(ctx, {})

    result = skeleton.handle(ctx, {"full": True})

    assert result.success
    assert "reaproveitado(s)" not in result.summary


def test_skeleton_truncates_markdown_over_budget(tmp_path, monkeypatch):
    ctx = _context(tmp_path)
    monkeypatch.setattr(skeleton, "SKELETON_BUDGET", 400)

    skeleton.handle(ctx, {})

    text = (tmp_path / "ws" / "knowledge" / "skeleton" / "SKELETON.md").read_text(
        encoding="utf-8"
    )
    assert "[truncado:" in text


def test_skeleton_uses_stack_profile(tmp_path):
    repo = tmp_path / "repo" / "src"
    repo.mkdir(parents=True)
    (repo / "Foo.java").write_text(
        "package x;\n"
        "import java.util.List;\n"
        "public class Foo {\n"
        "  public int bar(int x) { return x; }\n"
        "}\n",
        encoding="utf-8",
    )
    ctx = TaskContext(
        config={"legacy": {"repo_path": str(repo), "stack": "java-oracle"}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )

    result = skeleton.handle(ctx, {})

    assert result.success
    data = json.loads(
        (tmp_path / "ws" / "knowledge" / "skeleton" / "project.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["stack"] == "java-oracle"
    assert set(data["files_index"]) == {"Foo.java"}
    entry = data["files_index"]["Foo.java"]
    assert {"Foo", "bar"} <= {item["name"] for item in entry["symbols"]}
    assert "import java.util.List;" in entry["imports"]

    markdown = (tmp_path / "ws" / "knowledge" / "skeleton" / "SKELETON.md").read_text(
        encoding="utf-8"
    )
    assert "Java/Oracle" in markdown


def test_skeleton_reports_unknown_stack(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    ctx = TaskContext(
        config={"legacy": {"repo_path": str(repo), "stack": "cobol"}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )

    result = skeleton.handle(ctx, {})

    assert result.success is False
    assert "legacy.stack" in result.summary


def test_skeleton_reads_php_with_mixed_html(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "relatorio.php").write_text(
        "<?php\n"
        "function montar_relatorio($conn) {\n"
        '    $sql = "SELECT * FROM tb_alugueis";\n'
        "?>\n"
        "<script>var x = '<?php echo 1; ?>';</script>\n"
        "<?php\n"
        "}\n"
        "class Relatorio {\n"
        "    public function depois_do_html() {\n"
        '        $q = "SELECT * FROM tb_clientes";\n'
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    ctx = TaskContext(
        config={"legacy": {"repo_path": str(repo)}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )

    result = skeleton.handle(ctx, {})

    assert result.success
    data = json.loads(
        (tmp_path / "ws" / "knowledge" / "skeleton" / "project.json").read_text(
            encoding="utf-8"
        )
    )
    entry = data["files_index"]["relatorio.php"]
    assert {"montar_relatorio", "Relatorio", "depois_do_html"} <= {
        item["name"] for item in entry["symbols"]
    }
    assert {"tb_alugueis", "tb_clientes"} <= set(entry["tables"])
    # O cache de uma versão antiga do parser não é reaproveitado.
    data["version"] = 2
    (tmp_path / "ws" / "knowledge" / "skeleton" / "project.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    result = skeleton.handle(ctx, {})
    assert "reaproveitado(s)" not in result.summary


def _split_context(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for folder in ("cadastro", "aluguel", "relatorios"):
        directory = repo / folder
        directory.mkdir()
        for number in range(1, 21):
            (directory / f"arquivo{number:02d}.php").write_text(
                "<?php\n"
                f"function {folder}_funcao_{number}() {{\n"
                '    $sql = "SELECT * FROM tb_veiculos";\n'
                "}\n",
                encoding="utf-8",
            )
    return TaskContext(
        config={"legacy": {"repo_path": str(repo)}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def test_skeleton_split_map_writes_parts_and_index(tmp_path):
    ctx = _split_context(tmp_path)

    result = skeleton.handle(ctx, {"split_map": True, "map_part_chars": 2000})

    assert result.success
    skeleton_path = tmp_path / "ws" / "knowledge" / "skeleton"
    index = (skeleton_path / "MAP.md").read_text(encoding="utf-8")
    parts = sorted((skeleton_path / "map").glob("part-*.md"))

    assert "índice" in index
    assert len(parts) > 1
    assert "map/part-001.md" in index
    assert all(len(p.read_text(encoding="utf-8")) <= 2200 for p in parts)
    # Todos os arquivos aparecem no mapa completo (não só os 5 mais relevantes).
    all_parts = "\n".join(p.read_text(encoding="utf-8") for p in parts)
    assert all_parts.count("- `arquivo") == 60

    map_result = skeleton.handle(
        ctx, {"level": "map", "split_map": True, "map_part_chars": 2000}
    )
    assert map_result.success and "índice" in map_result.details


def test_skeleton_split_map_level_part_returns_slice(tmp_path):
    ctx = _split_context(tmp_path)

    result = skeleton.handle(ctx, {"split_map": True, "map_part_chars": 2000})
    assert result.success

    part = skeleton.handle(ctx, {"level": "part", "part": 1})
    assert part.success and "part-001.md" in part.summary
    assert "## " in part.details

    by_dir = skeleton.handle(ctx, {"level": "part", "path": "relatorios"})
    assert by_dir.success
    assert "relatorios/" in by_dir.details

    missing = skeleton.handle(ctx, {"level": "part", "part": 999})
    assert missing.success is False


def test_skeleton_disabling_split_removes_old_parts(tmp_path):
    ctx = _split_context(tmp_path)
    skeleton.handle(ctx, {"split_map": True, "map_part_chars": 2000})
    assert (tmp_path / "ws" / "knowledge" / "skeleton" / "map").is_dir()

    skeleton.handle(ctx, {"split_map": False})

    parts = list((tmp_path / "ws" / "knowledge" / "skeleton" / "map").glob("*.md"))
    assert parts == []
