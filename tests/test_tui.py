"""Testes da TUI: quebra de linha, reflow, busca, histórico e status."""

import asyncio
import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tui_app import MyCLIApp
from tui_log import WrappingRichLog


class FakeRegistry:
    def __init__(self):
        self._commands = {
            "/echo": SimpleNamespace(description="Ecoa o texto"),
            "/fail": SimpleNamespace(description="Sempre falha"),
        }

    def all(self):
        return self._commands

    def get(self, name):
        return self._commands.get(name)


class FakeExecutor:
    def __init__(self):
        self.registry = FakeRegistry()
        self.last_result = (True, None)

    def execute(self, command):
        if command.startswith("/fail"):
            self.last_result = (False, {"error": "falha proposital"})
            return "[red]falhou[/red]"
        self.last_result = (True, None)
        return "ok"


def make_app(tmp_path, monkeypatch):
    monkeypatch.setenv("CRIVONANSKY_HISTORY", str(tmp_path / "history.json"))
    monkeypatch.setenv("CRIVONANSKY_OUTPUT_DIR", str(tmp_path / "out"))
    return MyCLIApp(FakeExecutor())


def test_output_wraps_and_reflows(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(40, 20)) as pilot:
            log = app.query_one("#output", WrappingRichLog)
            log.write("x" * 200 + " " + "[red]" + "y" * 200 + "[/red]")
            await pilot.pause()

            region = log.scrollable_content_region.width
            assert region > 0
            assert max(len(line.text) for line in log.lines) <= region

            before = len(log.lines)
            await pilot.resize_terminal(100, 20)
            await pilot.pause(0.3)

            region = log.scrollable_content_region.width
            assert max(len(line.text) for line in log.lines) <= region
            assert len(log.lines) < before

    asyncio.run(scenario())


def test_progress_preserves_literal_task_prefix(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(40, 20)) as pilot:
            log = app.query_one("#output", WrappingRichLog)
            # executa numa thread como o worker real, sem bloquear o event loop
            # (``call_from_thread`` espera o loop processar a mensagem).
            await asyncio.to_thread(app._write_progress, "[db:links] 10/20")
            await pilot.pause()

            text = "\n".join(line.text for line in log.lines)
            assert "[db:links]" in text
            assert log.export_text() == "[db:links] 10/20"

    asyncio.run(scenario())


def test_search_highlights_without_losing_content(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(80, 20)) as pilot:
            log = app.query_one("#output", WrappingRichLog)
            log.write("alpha beta")
            log.write("gama beta")
            await pilot.pause()

            assert log.set_search("beta") == 2
            found = log.find_next()
            assert found is not None
            assert "beta" in log.lines[found].text

            assert log.set_search("") == 0
            text = "\n".join(line.text for line in log.lines)
            assert "alpha beta" in text

    asyncio.run(scenario())


def test_toggle_wrap_and_clear(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(40, 20)) as pilot:
            log = app.query_one("#output", WrappingRichLog)
            log.write("x" * 120)
            await pilot.pause()
            wrapped_lines = len(log.lines)

            await pilot.press("f4")
            await pilot.pause()
            assert log.wrapping is False
            assert len(log.lines) <= wrapped_lines

            await pilot.press("f4")
            await pilot.pause()
            assert log.wrapping is True

            await pilot.press("ctrl+l")
            await pilot.pause()
            assert log.lines == []
            assert log._history == []

    asyncio.run(scenario())


def test_dropdown_tab_completion_and_single_enter(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(80, 20)) as pilot:
            app.input.value = "/ec"
            await pilot.pause()
            assert app.dropdown.display is True

            await pilot.press("tab")
            await pilot.pause()
            assert app.input.value == "/echo"
            assert app.dropdown.display is False

            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            log = app.query_one("#output", WrappingRichLog)
            text = "\n".join(line.text for line in log.lines)
            assert "> /echo" in text
            assert "ok" in text

    asyncio.run(scenario())


def test_malformed_markup_falls_back_to_literal_text(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(60, 20)) as pilot:
            log = app.query_one("#output", WrappingRichLog)
            log.write("[/red] saída crua do comando")
            await pilot.pause()
            text = "\n".join(line.text for line in log.lines)
            assert "[/red] saída crua do comando" in text

    asyncio.run(scenario())


def test_history_navigation_does_not_open_dropdown(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(80, 20)) as pilot:
            app.command_history = ["/echo --x", "/fail"]
            app.history_index = -1

            app._history_prev()
            await pilot.pause()
            assert app.input.value == "/fail"
            assert app.dropdown.display is False

            app._history_prev()
            await pilot.pause()
            assert app.input.value == "/echo --x"
            assert app.dropdown.display is False

    asyncio.run(scenario())


def test_history_is_persisted(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    history_file = tmp_path / "history.json"

    async def scenario():
        async with app.run_test(size=(80, 20)) as pilot:
            app.input.value = "/echo"
            await pilot.press("enter")  # comando completo executa direto
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert app.command_history == ["/echo"]
        assert json.loads(history_file.read_text(encoding="utf-8")) == ["/echo"]

    asyncio.run(scenario())


def test_status_reports_success_and_failure(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            app._start_spinner("/echo")
            app._tick_spinner()
            assert "executando" in str(app.status_label.render())

            app._finish_command("/echo", "ok", True, 0.4)
            assert "✔" in str(app.status_label.render())

            app._finish_command("/fail", "", False, 0.4)
            assert "falhou" in str(app.status_label.render())

    asyncio.run(scenario())


def test_save_output_writes_plain_text(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(80, 20)) as pilot:
            log = app.query_one("#output", WrappingRichLog)
            log.write("[cyan]> /help[/cyan]")
            log.write("Comandos disponíveis")
            await pilot.pause()

            app.action_save_output()
            files = list((tmp_path / "out").glob("crivonansky-output-*.txt"))
            assert len(files) == 1
            content = files[0].read_text(encoding="utf-8")
            assert "> /help" in content
            assert "Comandos disponíveis" in content

    asyncio.run(scenario())


def test_header_becomes_compact_on_narrow_terminals(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)

    async def scenario():
        async with app.run_test(size=(100, 20)) as pilot:
            assert app.header.has_class("compact") is False
            await pilot.resize_terminal(50, 20)
            await pilot.pause()
            assert app.header.has_class("compact") is True
            await pilot.resize_terminal(100, 20)
            await pilot.pause()
            assert app.header.has_class("compact") is False

    asyncio.run(scenario())
