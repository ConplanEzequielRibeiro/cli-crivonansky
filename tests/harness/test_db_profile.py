"""Testes do snapshot/consulta por dialeto (F6.5)."""

import json

import pytest

from commands.complements.harness_core.runner import ProcessResult
from commands.complements.harness.tasks import db
from commands.complements.harness_core.task_types import TaskContext


def _ctx(tmp_path, legacy):
    return TaskContext(
        config={"legacy": legacy},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def test_parse_dump_postgres():
    sql = (
        "CREATE TABLE cidade (\n"
        "  id serial PRIMARY KEY,\n"
        "  nome varchar(80) NOT NULL\n"
        ");\n"
        "CREATE TABLE cliente (\n"
        "  id serial PRIMARY KEY,\n"
        "  nome varchar(100) NOT NULL,\n"
        "  id_cidade integer,\n"
        "  CONSTRAINT fk_cidade FOREIGN KEY (id_cidade) REFERENCES cidade (id)\n"
        ");\n"
    )

    catalog = db.parse_dump(sql, database="legacy", dialect="postgres")

    assert catalog["dialect"] == "postgres"
    tables = {table["name"]: table for table in catalog["tables"]}
    assert set(tables) == {"cidade", "cliente"}
    cliente = tables["cliente"]
    assert [column["name"] for column in cliente["columns"]] == [
        "id",
        "nome",
        "id_cidade",
    ]
    assert cliente["foreign_keys"][0]["ref_table"] == "cidade"
    assert cliente["foreign_keys"][0]["ref_columns"] == ["id"]


def test_parse_dump_tsql():
    sql = "CREATE TABLE dbo.Cliente (id int PRIMARY KEY, nome nvarchar(100) NOT NULL);\n"

    catalog = db.parse_dump(sql, database="legacy", dialect="tsql")

    assert catalog["dialect"] == "tsql"
    assert [table["name"] for table in catalog["tables"]] == ["Cliente"]
    assert catalog["tables"][0]["columns"][1]["nullable"] is False


def test_snapshot_uses_dump_for_tsql(tmp_path):
    dump = tmp_path / "dump.sql"
    dump.write_text(
        "CREATE TABLE Cliente (id int PRIMARY KEY, nome nvarchar(100));\n",
        encoding="utf-8",
    )
    ctx = _ctx(
        tmp_path,
        {"stack": "dotnet-sqlserver", "db_name": "legacy", "schema_dump": str(dump)},
    )

    result = db.handle_snapshot(ctx, {})

    assert result.success
    catalog = json.loads(
        (tmp_path / "ws" / "knowledge" / "db" / "schema-catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert catalog["dialect"] == "tsql"
    assert catalog["extracted_from"]["dialect"] == "tsql"
    assert "tsql" in result.summary


def test_snapshot_live_unsupported_for_oracle(tmp_path):
    ctx = _ctx(tmp_path, {"stack": "java-oracle", "db_container": "oracle"})

    result = db.handle_snapshot(ctx, {"source": "live"})

    assert result.success is False
    assert result.status == "unavailable"
    assert "oracle" in result.summary


def test_postgres_rows_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_DB_USER", "legacy")
    monkeypatch.setenv("HARNESS_DB_PASSWORD", "secret")
    ctx = _ctx(
        tmp_path,
        {
            "stack": "ruby-postgres",
            "db_container": "pg",
            "db_name": "legacy",
            "db_user_env": "HARNESS_DB_USER",
            "db_password_env": "HARNESS_DB_PASSWORD",
        },
    )
    captured = {}

    def fake_run(cmd, timeout=60):
        captured["cmd"] = cmd
        return ProcessResult(0, "a\tb\n", "")

    monkeypatch.setattr(db, "run_process", fake_run)

    rows = db._postgres_rows(ctx, "SELECT 1")

    assert rows == [["a", "b"]]
    cmd = captured["cmd"]
    assert "PGPASSWORD=secret" in cmd
    assert "psql" in cmd
    assert "-d" in cmd and "legacy" in cmd


def test_db_rows_dispatch(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, {})
    monkeypatch.setattr(db, "_mysql_rows", lambda ctx, sql: [["mysql"]])
    monkeypatch.setattr(db, "_postgres_rows", lambda ctx, sql: [["pg"]])

    assert db._db_rows(ctx, "SELECT 1", "mysql") == [["mysql"]]
    assert db._db_rows(ctx, "SELECT 1", "postgres") == [["pg"]]
    with pytest.raises(RuntimeError):
        db._db_rows(ctx, "SELECT 1", "tsql")


def test_postgres_snapshot_builds_catalog(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, {"stack": "ruby-postgres", "db_name": "legacy"})
    responses = [
        [["cliente", "Cadastro de clientes", "10"]],
        [
            ["cliente", "id", "integer", "NO", "nextval('cliente_id_seq')"],
            ["cliente", "nome", "character varying", "NO", ""],
        ],
        [
            ["cliente", "cliente_pkey", "PRIMARY KEY", "id"],
            ["cliente", "cliente_nome_key", "UNIQUE", "nome"],
        ],
        [["cliente", "id_cidade", "cidade", "id", "fk_cidade"]],
        [],
    ]
    monkeypatch.setattr(db, "_postgres_rows", lambda ctx, sql: responses.pop(0))

    catalog = db.snapshot_live(ctx, "postgres")

    table = catalog["tables"][0]
    assert table["name"] == "cliente"
    assert table["comment"] == "Cadastro de clientes"
    assert {column["name"] for column in table["columns"]} == {"id", "nome"}
    assert next(column for column in table["columns"] if column["name"] == "id")["key"] == "PRI"
    assert [index["name"] for index in table["indexes"]] == [
        "cliente_pkey",
        "cliente_nome_key",
    ]
    assert table["foreign_keys"][0]["ref_table"] == "cidade"


def test_query_unavailable_for_tsql(tmp_path):
    ctx = _ctx(tmp_path, {"stack": "dotnet-sqlserver"})

    result = db.handle_query(ctx, {"sql": "SELECT * FROM Cliente"})

    assert result.success is False
    assert result.status == "unavailable"
    assert "tsql" in result.summary


def test_query_uses_profile_dialect(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, {"stack": "ruby-postgres", "db_container": "pg"})
    captured = {}

    def fake_run(cmd, timeout=60):
        captured["cmd"] = cmd
        return ProcessResult(0, "1\n", "")

    monkeypatch.setattr(db, "run_process", fake_run)

    result = db.handle_query(ctx, {"sql": "SELECT id FROM cliente"})

    assert result.success
    assert "psql" in captured["cmd"]
    assert result.summary == "1 linha(s) retornada(s)"


def test_read_text_strips_utf8_bom(tmp_path):
    from commands.complements.harness_core.util import read_text

    dump = tmp_path / "dump.sql"
    dump.write_bytes(b"\xef\xbb\xbfCREATE TABLE x (id int);\n")

    assert read_text(str(dump)).startswith("CREATE TABLE x")
