"""Testes ponta a ponta dos perfis embutidos (F6.8).

Cada caso roda `code:skeleton` + `db:links` em um repositório mínimo da stack e
confere símbolos, imports e vínculos com tabela.
"""

import json

from commands.complements.harness.tasks import links, skeleton
from commands.complements.harness_core.task_types import TaskContext


def _ctx(tmp_path, stack, files, extra=None):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    return TaskContext(
        config={
            "legacy": {
                "repo_path": str(repo),
                "stack": stack,
                "db_name": "legacy",
                **(extra or {}),
            }
        },
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def _skeleton_entry(tmp_path, name):
    data = json.loads(
        (tmp_path / "ws" / "knowledge" / "skeleton" / "project.json").read_text(
            encoding="utf-8"
        )
    )
    return data, data["files_index"][name]


def _links(tmp_path):
    return json.loads(
        (tmp_path / "ws" / "knowledge" / "links" / "code-db-links.json").read_text(
            encoding="utf-8"
        )
    )


def _includes(tmp_path):
    return json.loads(
        (tmp_path / "ws" / "knowledge" / "links" / "includes.json").read_text(
            encoding="utf-8"
        )
    )


def test_dotnet_sqlserver_end_to_end(tmp_path):
    ctx = _ctx(
        tmp_path,
        "dotnet-sqlserver",
        {
            "src/ClienteRepo.cs": (
                "using System;\n"
                "namespace N {\n"
                "  public class ClienteRepo {\n"
                "    public void Salvar() {\n"
                "      var sql = \"INSERT INTO tb_clientes (nome) VALUES ('x')\";\n"
                "    }\n"
                "  }\n"
                "}\n"
            )
        },
    )

    assert skeleton.handle(ctx, {}).success
    assert links.handle(ctx, {}).success

    data, entry = _skeleton_entry(tmp_path, "src/ClienteRepo.cs")
    assert data["stack"] == "dotnet-sqlserver"
    assert {"ClienteRepo", "Salvar"} <= {item["name"] for item in entry["symbols"]}
    assert "using System;" in entry["imports"]

    link = _links(tmp_path)[0]
    assert link["table"] == "tb_clientes"
    assert link["symbol"] == "Salvar"
    assert link["operation"] == "write"

    include = _includes(tmp_path)[0]
    assert include["type"] == "using"
    assert include["target"] == "System"


def test_ruby_postgres_end_to_end(tmp_path):
    ctx = _ctx(
        tmp_path,
        "ruby-postgres",
        {
            "app/cliente_repo.rb": (
                "require 'json'\n"
                "class ClienteRepo\n"
                "  def salvar\n"
                "    sql = \"INSERT INTO tb_clientes (nome) VALUES ('x')\"\n"
                "  end\n"
                "end\n"
            )
        },
    )

    assert skeleton.handle(ctx, {}).success
    assert links.handle(ctx, {}).success

    data, entry = _skeleton_entry(tmp_path, "app/cliente_repo.rb")
    assert data["stack"] == "ruby-postgres"
    assert {"ClienteRepo", "salvar"} <= {item["name"] for item in entry["symbols"]}
    assert "require 'json'" in entry["imports"]

    link = _links(tmp_path)[0]
    assert link["table"] == "tb_clientes"
    assert link["symbol"] == "salvar"

    include = _includes(tmp_path)[0]
    assert include["type"] == "require"
    assert include["target"] == "json"


def test_go_via_custom_profile_end_to_end(tmp_path):
    ctx = _ctx(
        tmp_path,
        "custom",
        {
            "cmd/app/main.go": (
                "package main\n"
                'import "database/sql"\n'
                "type ClienteRepo struct{}\n"
                "func (r ClienteRepo) Salvar() {\n"
                '    sql := "INSERT INTO tb_clientes (nome) VALUES (\'x\')"\n'
                "}\n"
            )
        },
        extra={
            "extensions": [".go"],
            "languages": {".go": "go"},
            "db_dialect": "postgres",
        },
    )

    assert skeleton.handle(ctx, {}).success
    assert links.handle(ctx, {}).success

    data, entry = _skeleton_entry(tmp_path, "cmd/app/main.go")
    assert data["stack"] == "custom"
    assert {"ClienteRepo", "Salvar"} <= {item["name"] for item in entry["symbols"]}
    assert 'import "database/sql"' in entry["imports"]

    link = _links(tmp_path)[0]
    assert link["table"] == "tb_clientes"
    assert link["symbol"] == "Salvar"

    include = _includes(tmp_path)[0]
    assert include["type"] == "import"
    assert include["target"] == "database/sql"
