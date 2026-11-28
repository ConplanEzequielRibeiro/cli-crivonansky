"""`/help`: comandos + ajuda de cada plugin no bloco crivonansky-result."""

import sys
import types

from commands.help import HelpCommand
from core.command import Command
from core.registry import CommandRegistry


class _FakeCommand(Command):
    def __init__(self, name, description, help_text=""):
        super().__init__()
        self.name = name
        self.description = description
        self.help_text = help_text

    def execute(self, args):
        return True, None


def _registry():
    registry = CommandRegistry()
    registry.register(
        "harness",
        _FakeCommand("harness", "Mapeamento", "Uso: /harness\nLista o mapa."),
    )
    registry.register("task", _FakeCommand("task", "Tarefas", "Uso: /task start"))
    return registry


def _run(monkeypatch):
    command = HelpCommand()
    command.context = types.SimpleNamespace(registry=_registry())
    return command.execute([])


def _fake_clipboard(monkeypatch):
    copied: list[str] = []
    module = types.ModuleType("pyperclip")
    module.copy = copied.append
    module.paste = lambda: ""
    monkeypatch.setitem(sys.modules, "pyperclip", module)
    return copied


def test_help_lists_every_command_with_its_help_text(monkeypatch, capsys):
    copied = _fake_clipboard(monkeypatch)

    ok, data = _run(monkeypatch)
    printed = capsys.readouterr().out.strip()

    assert ok is True
    assert printed.startswith("```crivonansky-result")
    assert printed.endswith("```")
    assert "task: help" in printed
    assert "status: success" in printed
    assert "summary: \"ajuda de 2 comando(s)\"" in printed
    assert "Comandos disponíveis (2):" in printed
    assert "/harness - Mapeamento" in printed
    assert "Uso: /harness" in printed
    assert "Lista o mapa." in printed
    assert "/task - Tarefas" in printed
    assert "Uso: /task start" in printed
    assert data == {"count": 2, "clipboard": True}
    assert copied == [printed]


def test_help_keeps_details_indented_for_the_block(monkeypatch, capsys):
    _fake_clipboard(monkeypatch)

    _run(monkeypatch)
    printed = capsys.readouterr().out

    details = [line for line in printed.splitlines() if line.startswith("  ")]
    assert "  Comandos disponíveis (2):" in details
    assert "  Uso: /harness" in details


def test_help_without_clipboard_still_returns_the_block(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "pyperclip", None)

    ok, data = _run(monkeypatch)
    printed = capsys.readouterr().out.strip()

    assert ok is True
    assert printed.startswith("```crivonansky-result")
    assert data["clipboard"] is False


def test_result_block_truncates_with_a_marker():
    from core import result_block

    text, truncated = result_block.truncate("x" * 400, 200)

    assert truncated is True
    assert "[truncado:" in text
    assert text.endswith("]")
