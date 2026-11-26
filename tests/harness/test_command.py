"""Testes do comando /harness (helpers de contexto e help)."""

import json
import sys
from types import SimpleNamespace

from commands.harness import HarnessCommand
from commands.complements.harness.task_types import TaskResult


def test_help_lists_lifecycle_and_contract_subcommands():
    text = HarnessCommand().help_text

    for subcommand in (
        "install",
        "start",
        "stop",
        "prepare",
        "preprocess",
        "config",
        "exec",
        "run",
        "ask",
        "tasks",
        "runs",
        "hooks",
        "env:check",
    ):
        assert subcommand in text


def test_start_forwards_no_docker_flag(monkeypatch):
    captured = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return TaskResult(True, "ok")

    monkeypatch.setattr("commands.harness.ops.start", fake_start)

    ok, data = HarnessCommand().execute(["start", "--no-docker"])

    assert ok is True
    assert captured["no_docker"] is True
    assert captured["with_rag"] is False
    assert data["summary"] == "ok"


def test_db_context_summarizes_schema_catalog(tmp_path):
    knowledge = tmp_path / "knowledge" / "db"
    knowledge.mkdir(parents=True)
    (knowledge / "schema-catalog.json").write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "name": "tb_clientes",
                        "comment": "Clientes",
                        "columns": [
                            {"name": "id_cli", "type": "INT"},
                            {"name": "nome", "type": "VARCHAR(120)"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    text = HarnessCommand()._db_context(SimpleNamespace(workspace=str(tmp_path)))

    assert "### tb_clientes" in text
    assert "Clientes" in text
    assert "id_cli INT" in text
    assert "nome VARCHAR(120)" in text


def test_db_context_reports_missing_catalog(tmp_path):
    text = HarnessCommand()._db_context(SimpleNamespace(workspace=str(tmp_path)))

    assert "schema-catalog.json não encontrado" in text


def test_parse_run_args_accepts_no_clipboard():
    task, params, flags = HarnessCommand()._parse_run_args(
        ["code:skeleton", "--no-clipboard"]
    )

    assert task == "code:skeleton"
    assert params == {}
    assert flags["no_clipboard"] is True


def test_single_no_clipboard_uses_stdout_sink(monkeypatch):
    captured = {}

    class FakeEngine:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def handle_block(self, raw, yes_allowed=True):
            return "ok", "success"

    monkeypatch.setattr(
        "commands.complements.harness.engine.HarnessEngine", FakeEngine
    )

    ok, _data = HarnessCommand()._single(None, "code:skeleton", {}, no_clipboard=True)

    assert ok is True
    assert captured["sinks"] == ["stdout"]


def test_single_keeps_config_sinks_by_default(monkeypatch):
    captured = {}

    class FakeEngine:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def handle_block(self, raw, yes_allowed=True):
            return "ok", "success"

    monkeypatch.setattr(
        "commands.complements.harness.engine.HarnessEngine", FakeEngine
    )

    HarnessCommand()._single(None, "code:skeleton", {})

    assert captured["sinks"] is None


def test_ask_no_clipboard_does_not_copy(monkeypatch, tmp_path):
    class FakeEngine:
        def __init__(self, **kwargs):
            self.config = {}
            self.workspace = str(tmp_path)

    monkeypatch.setattr(
        "commands.complements.harness.engine.HarnessEngine", FakeEngine
    )

    class Boom:
        @staticmethod
        def copy(_text):
            raise AssertionError("pyperclip.copy não deveria ser chamado")

    monkeypatch.setitem(sys.modules, "pyperclip", Boom)

    ok, data = HarnessCommand()._ask(
        None, ["pergunta?", "--context", " ", "--no-clipboard"]
    )

    assert ok is True
    assert data["copied"] is False
