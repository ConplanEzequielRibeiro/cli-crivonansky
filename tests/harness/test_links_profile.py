"""Testes do db:links orientado por perfil de stack (F6.4)."""

import json

from commands.complements.harness.tasks import links
from commands.complements.harness_core.task_types import TaskContext


def _ctx(tmp_path, config_legacy, filename, source):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    target = repo / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")

    return TaskContext(
        config={"legacy": {"repo_path": str(repo), **config_legacy}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def _read_links(tmp_path):
    return json.loads(
        (tmp_path / "ws" / "knowledge" / "links" / "code-db-links.json").read_text(
            encoding="utf-8"
        )
    )


def _read_includes(tmp_path):
    return json.loads(
        (tmp_path / "ws" / "knowledge" / "links" / "includes.json").read_text(
            encoding="utf-8"
        )
    )


def test_links_uses_profile_extensions_language_and_dialect(tmp_path):
    ctx = _ctx(
        tmp_path,
        {
            "stack": "custom",
            "extensions": [".java"],
            "sql_extensions": [".java"],
            "languages": {".java": "java"},
            "db_dialect": "postgres",
        },
        "src/ClienteService.java",
        "package x;\n"
        "import java.util.List;\n"
        "public class ClienteService {\n"
        "  public void salvar() {\n"
        "    String sql = \"INSERT INTO tb_clientes (nome) VALUES ('x')\";\n"
        "  }\n"
        "}\n",
    )

    result = links.handle(ctx, {})

    assert result.success
    assert [item["table"] for item in _read_links(tmp_path)] == ["tb_clientes"]
    assert "stack: custom | dialeto SQL: postgres" in result.details

    includes = _read_includes(tmp_path)
    assert includes == [
        {
            "file": "src/ClienteService.java",
            "line": 2,
            "type": "import",
            "target": "java.util.List",
        }
    ]


def test_links_ignores_extensions_outside_profile(tmp_path):
    ctx = _ctx(
        tmp_path,
        {},
        "src/ClienteService.java",
        "class ClienteService {\n"
        "  void salvar() {\n"
        "    String sql = \"INSERT INTO tb_clientes (nome) VALUES ('x')\";\n"
        "  }\n"
        "}\n",
    )

    result = links.handle(ctx, {})

    assert result.success
    assert _read_links(tmp_path) == []
    assert _read_includes(tmp_path) == []


def test_links_uses_dialect_for_confidence(tmp_path):
    source = "class Repo {\n  void q() {\n    var sql = \"SELECT TOP 10 * FROM tb_x\";\n  }\n}\n"

    tsql_ctx = _ctx(
        tmp_path / "a",
        {"stack": "dotnet-sqlserver"},
        "Repo.cs",
        source,
    )
    links.handle(tsql_ctx, {})
    tsql_links = _read_links(tmp_path / "a")

    mysql_ctx = _ctx(
        tmp_path / "b",
        {
            "stack": "custom",
            "extensions": [".java"],
            "sql_extensions": [".java"],
            "languages": {".java": "java"},
            "db_dialect": "mysql",
        },
        "Repo.java",
        source,
    )
    links.handle(mysql_ctx, {})
    mysql_links = _read_links(tmp_path / "b")

    assert tsql_links[0]["confidence"] == "parsed"
    assert mysql_links[0]["confidence"] == "heuristic"


def test_links_reports_unknown_stack(tmp_path):
    ctx = TaskContext(
        config={
            "legacy": {"repo_path": str(tmp_path / "repo"), "stack": "cobol"},
        },
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )

    result = links.handle(ctx, {})

    assert result.success is False
    assert "legacy.stack" in result.summary
