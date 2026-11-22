"""Testes do esqueleto do código (code:skeleton)."""

import json

from commands.complements.harness.tasks import skeleton
from commands.complements.harness.task_types import TaskContext


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
    assert "(truncado)" in text


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
