"""TUI do Crivonansky (Textual).

Layout: cabeçalho, painel de saída com quebra de linha, barra de busca,
prompt de comando, dropdown de comandos e barra de status.

Atalhos:
    Ctrl+L  limpa o log
    Ctrl+F  busca no log (Enter = próxima ocorrência, Esc = fecha)
    Ctrl+S  salva o log em texto puro
    F2      volta ao fim do log e retoma o auto-scroll
    F4      liga/desliga a quebra de linha
    Ctrl+Q  sai
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import platformdirs
from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from tui_log import WrappingRichLog
from tui_logo import banner


class PromptInput(Input):
    """Input de comando: Tab completa o item destacado no dropdown.

    O ``Input`` não trata Tab; sem isso o binding de ``focus_next`` da Screen
    consumiria a tecla antes do app.
    """

    def on_key(self, event) -> None:
        if event.key != "tab":
            return
        complete = getattr(self.app, "complete_from_dropdown", None)
        if complete is not None and complete():
            event.stop()


class ConfirmScreen(ModalScreen[bool]):
    """Confirmação de tarefa de escrita dentro da TUI (substitui o input())."""

    BINDINGS = [
        Binding("y", "yes", "Executar", show=False),
        Binding("n", "no", "Cancelar", show=False),
        Binding("escape", "no", "Cancelar", show=False),
    ]

    def __init__(self, task: str, params: dict, preview: str | None = None):
        super().__init__()
        self._task = task
        self._params = params or {}
        self._preview = preview

    def compose(self) -> ComposeResult:
        body = [
            f"Tarefa de escrita: {self._task}",
            "",
            json.dumps(self._params, ensure_ascii=False, indent=2, default=str),
        ]
        if self._preview:
            body.extend(["", self._preview])
        yield Container(
            Static("\n".join(body), id="confirm-text"),
            Horizontal(
                Button("Executar (y)", id="yes", variant="success"),
                Button("Cancelar (n)", id="no"),
                id="confirm-buttons",
            ),
            id="confirm-box",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class MyCLIApp(App):
    TITLE = "CLI Crivonansky"

    BINDINGS = [
        Binding("ctrl+l", "clear_output", "Limpar", show=False),
        Binding("ctrl+f", "search", "Buscar", show=False),
        Binding("ctrl+s", "save_output", "Salvar", show=False),
        Binding("f2", "scroll_end", "Fim do log", show=False),
        Binding("f4", "toggle_wrap", "Quebra de linha", show=False),
    ]

    HISTORY_LIMIT = 300
    HISTORY_ENV = "CRIVONANSKY_HISTORY"
    EXPORT_DIR_ENV = "CRIVONANSKY_OUTPUT_DIR"
    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    IDLE_STATUS = " /help • ctrl+f buscar • ctrl+s salvar • f4 quebra • ctrl+q sair"

    CSS = """
    Screen {
        layout: vertical;
    }

    #header {
        layout: horizontal;
        height: 3;
        background: $primary;
        color: $text;
        padding: 0 1;
        align: center middle;
    }

    #header.compact {
        height: 1;
    }

    #header.compact #app-title {
        content-align: left middle;
    }

    #app-title {
        content-align: center middle;
        text-style: bold;
        width: 1fr;
    }

    #output {
        width: 100%;
        height: 1fr;
        border: solid $primary;
    }

    #search-bar {
        display: none;
        layout: horizontal;
        height: 3;
        background: $panel;
        border-top: solid $primary;
    }

    #search-prompt {
        width: auto;
        min-width: 12;
        content-align: left middle;
        padding: 0 1;
        color: $primary;
        text-style: bold;
    }

    #search-input {
        width: 1fr;
        background: transparent;
        border: none;
        padding: 0 1;
    }

    #input-container {
        layout: horizontal;
        height: 3;
        background: $panel;
        border-top: solid $primary;
    }

    #prompt {
        width: 3;
        content-align: center middle;
        background: $panel;
        color: $primary;
        text-style: bold;
    }

    #input {
        width: 1fr;
        background: transparent;
        border: none;
        padding: 0 1;
    }

    #command-dropdown {
        display: none;
        height: auto;
        max-height: 12;
        min-width: 30;
        border: solid $primary;
        background: $panel;
        margin: 0 0 0 3;
    }

    #command-dropdown ListItem {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }

    #command-dropdown Horizontal {
        height: 1;
    }

    #command-dropdown .cmd-name {
        width: auto;
        padding-right: 2;
        text-style: bold;
    }

    #command-dropdown .cmd-desc {
        width: 1fr;
        color: $text-muted;
    }

    #command-dropdown ListItem.--highlight {
        background: $accent;
        color: $text;
        text-style: bold;
    }

    #command-dropdown ListItem.--highlight .cmd-desc {
        color: $text;
    }

    #status-bar {
        height: 1;
        background: $primary;
        color: $text;
    }

    #status-text {
        width: 100%;
        padding: 0 1;
        overflow-x: hidden;
    }

    ConfirmScreen {
        align: center middle;
    }

    #confirm-box {
        width: 90%;
        max-width: 110;
        max-height: 85%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
    }

    #confirm-text {
        height: auto;
        max-height: 70%;
        overflow-y: auto;
    }

    #confirm-buttons {
        height: 3;
        align: center middle;
    }

    #confirm-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, executor):
        super().__init__()
        self.executor = executor

    def compose(self) -> ComposeResult:
        yield Container(
            Label("CLI Crivonansky", id="app-title"),
            id="header"
        )
        yield WrappingRichLog(
            id="output", highlight=True, markup=True, max_lines=10_000
        )
        yield Container(
            Label("busca:", id="search-prompt"),
            Input(placeholder="texto (Enter próximo, Esc fecha)", id="search-input"),
            id="search-bar"
        )
        yield Container(
            Label("❯", id="prompt"),
            PromptInput(placeholder="", id="input"),
            id="input-container"
        )
        yield ListView(id="command-dropdown")
        yield Container(
            Label(self.IDLE_STATUS, id="status-text"),
            id="status-bar"
        )

    def on_mount(self):
        self.output = self.query_one("#output", WrappingRichLog)
        self.input = self.query_one("#input", PromptInput)
        self.dropdown = self.query_one("#command-dropdown", ListView)
        self.search_bar = self.query_one("#search-bar", Container)
        self.search_input = self.query_one("#search-input", Input)
        self.search_prompt = self.query_one("#search-prompt", Label)
        self.status_label = self.query_one("#status-text", Label)
        self.header = self.query_one("#header", Container)

        self.dropdown.display = False
        self.command_history: list[str] = self._load_history()
        self.history_index: int = -1
        self._suppress_dropdown = False

        self._search_timer = None
        self._status_timer = None
        self._status_reset_timer = None
        self._spinner_index = 0
        self._status_command = ""

        self._set_status(self.IDLE_STATUS)
        self._update_header(self.size.width)
        self._write_banner()
        self.input.focus()

        self._harness_engine = None
        try:
            from commands.complements.harness import engine as harness_engine

            self._harness_engine = harness_engine
            harness_engine.set_confirm_handler(self._confirm_harness)
        except Exception:  # noqa: BLE001 - harness opcional
            self._harness_engine = None

    def _confirm_harness(self, task: str, params: dict, preview: str | None = None) -> bool:
        """Chamado da worker thread: mostra a confirmação e espera a resposta."""
        done = threading.Event()
        answer = {"value": False}

        def show() -> None:
            def finish(value) -> None:
                answer["value"] = bool(value)
                done.set()

            try:
                self.push_screen(ConfirmScreen(task, params, preview), callback=finish)
            except Exception:  # noqa: BLE001 - app encerrando
                done.set()

        try:
            self.call_from_thread(show)
        except Exception:  # noqa: BLE001 - fora do loop da TUI
            return False

        done.wait(timeout=120)
        return answer["value"]

    def on_unmount(self):
        if getattr(self, "_harness_engine", None) is not None:
            self._harness_engine.set_confirm_handler(None)
        self._stop_spinner()
        self._stop_status_reset()
        self._write_history()

    def on_resize(self, event) -> None:
        self._update_header(event.size.width)

    def _write_banner(self) -> None:
        """Exibe a arte como texto inicial do log."""
        try:
            compact = 0 < self.size.width < 60
            self.output.write(banner(compact=compact))
        except Exception:  # noqa: BLE001 - app encerrando
            pass

    def _update_header(self, width: int) -> None:
        try:
            self.header.set_class(width < 60, "compact")
        except Exception:  # noqa: BLE001 - durante o shutdown
            pass

    # ------------------------------------------------------------------ teclado
    def on_key(self, event) -> None:
        if event.key == "escape" and self.search_bar.display:
            event.stop()
            self._close_search()
            return

        if self.search_bar.display:
            return

        if self.dropdown.display:
            if event.key == "down":
                event.stop()
                self._dropdown_next()
            elif event.key == "up":
                event.stop()
                self._dropdown_prev()
            elif event.key in ("escape",):
                event.stop()
                self._hide_dropdown()
            elif event.key == "tab":
                event.stop()
                self._apply_completion()
            return

        if event.key == "up":
            event.stop()
            self._history_prev()
        elif event.key == "down":
            event.stop()
            self._history_next()

    # ------------------------------------------------------------------ ações
    def action_clear_output(self) -> None:
        self._clear_output()

    def action_search(self) -> None:
        self._hide_dropdown()
        self.search_bar.display = True
        self.search_input.value = ""
        self.search_input.focus()
        self.search_prompt.update("busca:")
        self._set_status("digite para buscar • Enter próximo • Esc fecha")

    def action_save_output(self) -> None:
        directory = Path(
            os.environ.get(self.EXPORT_DIR_ENV) or Path.cwd()
        )
        name = f"crivonansky-output-{datetime.now():%Y%m%d-%H%M%S}.txt"
        path = directory / name
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(self.output.export_text() + "\n", encoding="utf-8")
        except OSError as exc:
            self._flash_status(f"erro ao salvar: {exc}", style="red")
            return
        self._flash_status(f"saída salva em {path}", style="green")

    def action_scroll_end(self) -> None:
        self.output.jump_to_end()

    def action_toggle_wrap(self) -> None:
        enabled = self.output.toggle_wrap()
        if enabled:
            self._flash_status("quebra de linha ativada", style="green")
        else:
            self._flash_status(
                "quebra de linha desativada (scroll horizontal)", style="yellow"
            )

    # ------------------------------------------------------------------ entrada
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._schedule_search(event.value)
            return
        if self._suppress_dropdown:
            self._suppress_dropdown = False
            return
        value = event.value.strip()
        if value.startswith("/"):
            self._show_dropdown(value)
        else:
            self.dropdown.display = False

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not self.dropdown.display:
            return
        self._select_item(event.item)

    async def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "search-input":
            self._search_next()
            return

        command = event.value.strip()

        if not command:
            return

        if self.dropdown.display and self.dropdown.children:
            highlighted = self._highlighted_name()
            if highlighted and highlighted != command:
                self._complete_with(highlighted)
                return
            self._hide_dropdown()

        if command == "/clear":
            self._clear_output()
            return

        if command == "/quit":
            self.exit()
            return

        self._remember_command(command)

        self.output.write(f"[cyan]> {escape(command)}[/cyan]")
        self.input.value = ""
        self._start_spinner(command)
        self._run_command(command)

    def _clear_output(self) -> None:
        self._hide_dropdown()
        self._close_search(focus=False)
        self.output.clear()
        self.input.value = ""
        self.input.focus()

    # ------------------------------------------------------------------ dropdown
    def _command_catalog(self) -> dict[str, str]:
        catalog: dict[str, str] = {}
        try:
            for name, command in self.executor.registry.all().items():
                catalog[name] = getattr(command, "description", "")
        except Exception:  # noqa: BLE001 - registry indisponível
            pass
        catalog.setdefault("/clear", "Limpa a saída")
        catalog.setdefault("/quit", "Sai da aplicação")
        return catalog

    def _show_dropdown(self, prefix: str):
        catalog = self._command_catalog()
        value = prefix.strip()
        # Não reexibe quando o texto já é exatamente um comando (nada a completar).
        matching = sorted(
            name
            for name in catalog
            if name.startswith(value) and name != value
        )
        self.dropdown.clear()
        for name in matching:
            self.dropdown.append(
                ListItem(
                    Horizontal(
                        Label(name, classes="cmd-name"),
                        Label(catalog.get(name, ""), classes="cmd-desc"),
                    )
                )
            )
        self.dropdown.display = bool(matching)
        if matching:
            self.dropdown.index = 0

    def _dropdown_next(self):
        if not self.dropdown.children:
            return
        idx = self.dropdown.index or 0
        self.dropdown.index = min(idx + 1, len(self.dropdown.children) - 1)

    def _dropdown_prev(self):
        if not self.dropdown.children:
            return
        idx = self.dropdown.index or 0
        self.dropdown.index = max(idx - 1, 0)

    def _hide_dropdown(self):
        self.dropdown.display = False

    def complete_from_dropdown(self) -> bool:
        """Completa com o item destacado; devolve True se completou."""
        return self._apply_completion()

    def _apply_completion(self) -> bool:
        name = self._highlighted_name()
        if not name:
            return False
        self._complete_with(name)
        return True

    def _highlighted_name(self) -> str | None:
        if not self.dropdown.display or not self.dropdown.children:
            return None
        item = self.dropdown.highlighted_child or self.dropdown.children[0]
        return self._item_name(item)

    @staticmethod
    def _item_name(item: ListItem) -> str | None:
        try:
            label = item.query_one(".cmd-name", Label)
            return str(label.render()).strip()
        except Exception:  # noqa: BLE001 - item inesperado
            return None

    def _select_item(self, item: ListItem) -> bool:
        name = self._item_name(item)
        if not name:
            return False
        self._complete_with(name)
        return True

    def _complete_with(self, command_name: str) -> None:
        # O Input.Changed é uma mensagem: marca a próxima mudança para que o
        # handler não reabra o dropdown de forma assíncrona.
        self._set_input_value(command_name)
        self._hide_dropdown()
        self.input.focus()

    def _set_input_value(self, value: str) -> None:
        if self.input.value != value:
            self._suppress_dropdown = True
        self.input.value = value
        self.input.cursor_position = len(value)

    # ------------------------------------------------------------------ histórico
    def _history_prev(self):
        if not self.command_history:
            return
        if self.history_index == -1:
            self.history_index = len(self.command_history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
        self._set_input_value(self.command_history[self.history_index])
        self.dropdown.display = False

    def _history_next(self):
        if not self.command_history or self.history_index == -1:
            return
        if self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            self._set_input_value(self.command_history[self.history_index])
        else:
            self.history_index = -1
            self._set_input_value("")
        self.dropdown.display = False

    def _history_path(self) -> Path | None:
        override = os.environ.get(self.HISTORY_ENV)
        if override:
            return Path(override)
        try:
            base = Path(platformdirs.user_data_dir("crivonansky", appauthor=False))
        except Exception:  # noqa: BLE001 - ambiente sem diretório de dados
            return None
        return base / "history.json"

    def _load_history(self) -> list[str]:
        path = self._history_path()
        if path is None:
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, str)][-self.HISTORY_LIMIT:]

    def _remember_command(self, command: str) -> None:
        if self.command_history and self.command_history[-1] == command:
            return
        self.command_history.append(command)
        if len(self.command_history) > self.HISTORY_LIMIT:
            del self.command_history[:-self.HISTORY_LIMIT]
        self._write_history()

    def _write_history(self) -> None:
        path = self._history_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.command_history, ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ busca
    def _schedule_search(self, query: str) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(
            0.2, lambda: self._apply_search(query)
        )

    def _apply_search(self, query: str) -> None:
        self._search_timer = None
        count = self.output.set_search(query)
        if query.strip():
            self.search_prompt.update(f"busca {count}:")
            if count:
                self.output.find_next(query)
        else:
            self.search_prompt.update("busca:")

    def _search_next(self) -> None:
        query = self.search_input.value.strip()
        if not query:
            return
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        total = self.output.set_search(query)
        found = self.output.find_next(query)
        if found is None:
            self.search_prompt.update("busca 0:")
        else:
            self.search_prompt.update(f"busca {total}:")

    def _close_search(self, focus: bool = True) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        if self.search_bar.display:
            self.search_bar.display = False
        self.output.set_search("")
        self.search_input.value = ""
        self.search_prompt.update("busca:")
        if focus:
            self.input.focus()
            self._set_status(self.IDLE_STATUS)

    # ------------------------------------------------------------------ execução
    @work(thread=True, exclusive=True)
    def _run_command(self, command: str) -> None:
        sink = None
        try:
            from commands.complements.harness import progress as harness_progress

            sink = harness_progress
            sink.set_sink(self._write_progress)
        except Exception:  # noqa: BLE001 - o harness pode não estar instalado
            sink = None

        started = time.perf_counter()
        try:
            result = self.executor.execute(command)
            success, _ = self.executor.last_result
        except Exception as exc:  # noqa: BLE001 - worker nunca deve morrer calado
            result = f"[red]Erro ao executar comando: {escape(str(exc))}[/red]"
            success = False
        finally:
            if sink is not None:
                sink.clear_sink(self._write_progress)
        elapsed = time.perf_counter() - started

        try:
            self.call_from_thread(
                self._finish_command, command, result, success, elapsed
            )
        except Exception:  # noqa: BLE001 - app encerrando
            pass

    def _write_progress(self, line: str) -> None:
        """Chamado do worker thread pelo módulo de progresso do harness.

        O texto é escapado para preservar prefixos literais como ``[db:links]``
        (sem escape, o Rich os interpretaria como marcação e os removeria).
        """
        try:
            self.call_from_thread(
                self.output.write, f"[dim]{escape(line)}[/dim]"
            )
        except Exception:  # noqa: BLE001 - app encerrando
            pass

    def _finish_command(
        self, command: str, result: str, success: bool, elapsed: float
    ) -> None:
        self._stop_spinner()
        if result:
            self.output.write(result)
        duration = self._format_elapsed(elapsed)
        if success:
            self._flash_status(f"✔ {command} ({duration})", style="green")
        else:
            self._flash_status(f"✘ {command} falhou ({duration})", style="red")

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        seconds = max(0.0, seconds)
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes, rest = divmod(int(seconds), 60)
        return f"{minutes}m{rest:02d}s"

    # ------------------------------------------------------------------ status
    def _set_status(self, text: str, style: str | None = None) -> None:
        safe = escape(text)
        if style:
            safe = f"[{style}]{safe}[/{style}]"
        try:
            self.status_label.update(safe)
        except Exception:  # noqa: BLE001 - app encerrando
            pass

    def _flash_status(
        self, text: str, style: str | None = None, revert: float = 4.0
    ) -> None:
        self._stop_spinner()
        self._set_status(text, style)
        self._stop_status_reset()
        self._status_reset_timer = self.set_timer(
            revert, lambda: self._set_status(self.IDLE_STATUS)
        )

    def _stop_status_reset(self) -> None:
        if self._status_reset_timer is not None:
            self._status_reset_timer.stop()
            self._status_reset_timer = None

    def _start_spinner(self, command: str) -> None:
        self._status_command = command
        self._spinner_index = 0
        self._stop_status_reset()
        if self._status_timer is not None:
            self._status_timer.stop()
        self._status_timer = self.set_interval(0.12, self._tick_spinner)

    def _tick_spinner(self) -> None:
        if not self._status_command:
            return
        frame = self.SPINNER[self._spinner_index % len(self.SPINNER)]
        self._spinner_index += 1
        self._set_status(
            f"{frame} executando: {self._status_command}", style="yellow"
        )

    def _stop_spinner(self) -> None:
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None
        self._status_command = ""
