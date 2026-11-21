"""Widget de saída da TUI.

O ``RichLog`` padrão renderiza e guarda as linhas **já quebradas**
(``wrap=False`` e ``min_width=78``), o que produz barra de rolagem horizontal.
``WrappingRichLog`` corrige isso e acrescenta os recursos usados pela TUI:

* quebra o texto na largura real do painel (``wrap=True``, ``min_width=0``);
* guarda o conteúdo bruto e re-renderiza quando a largura muda (reflow);
* destaca ocorrências de busca sem alterar o conteúdo guardado;
* pausa o auto-scroll quando o usuário rola para cima;
* exporta o histórico como texto puro.
"""

from __future__ import annotations

import re
from typing import Any

from rich.markup import MarkupError
from rich.text import Text
from textual import events
from textual.timer import Timer
from textual.widgets import RichLog

from core.output import strip_markup


class WrappingRichLog(RichLog):
    """``RichLog`` com quebra de linha automática e reflow ao redimensionar."""

    HIGHLIGHT_STYLE = "black on yellow"
    MAX_ENTRIES = 4000
    REFLOW_DELAY = 0.15

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("wrap", True)
        kwargs.setdefault("min_width", 0)
        super().__init__(**kwargs)
        self._history: list[Any] = []
        self._last_width: int | None = None
        self._rebuild_timer: Timer | None = None
        self._search_pattern = ""
        self._search_pos = 0
        self._rebuilding = False

    # ------------------------------------------------------------------ escrita
    def write(self, content: Any, *args: Any, **kwargs: Any) -> "WrappingRichLog":
        # Antes do primeiro resize o RichLog só enfileira renders deferidos e
        # os reescreve via ``self.write`` quando o tamanho é conhecido; registrar
        # agora duplicaria a entrada no histórico.
        if not self._rebuilding and getattr(self, "_size_known", False):
            self._history.append(content)
            overflow = len(self._history) - self.MAX_ENTRIES
            if overflow > 0:
                del self._history[:overflow]
        # ``_render`` aplica o destaque de busca e tolera markup inválido
        # (ex.: saída de log com ``[/algo]``), caindo para texto literal.
        return super().write(self._render(content), *args, **kwargs)

    def clear(self) -> "WrappingRichLog":
        self._history.clear()
        self._search_pos = 0
        return super().clear()

    # ------------------------------------------------------------------ reflow
    def on_resize(self, event: events.Resize) -> None:
        # Deixa o RichLog despejar os renders adiados antes de reconstruir.
        super().on_resize(event)
        width = event.size.width
        if self._last_width is None:
            self._last_width = width
            return
        if width != self._last_width:
            self._last_width = width
            self.rebuild()

    def rebuild(self, delay: float | None = None, immediate: bool = False) -> None:
        """Agenda a re-renderização do histórico na largura atual."""
        if immediate:
            if self._rebuild_timer is not None:
                self._rebuild_timer.stop()
                self._rebuild_timer = None
            self._rebuild()
            return
        if self._rebuild_timer is not None:
            self._rebuild_timer.stop()
        self._rebuild_timer = self.set_timer(
            self.REFLOW_DELAY if delay is None else delay, self._rebuild
        )

    def _rebuild(self) -> None:
        if not getattr(self, "_size_known", False):
            return
        at_bottom = self.is_vertical_scroll_end
        offset_y = self.scroll_offset.y
        self._rebuilding = True
        try:
            # ``super().clear()`` preserva ``_history`` e zera
            # ``_widest_line_width`` (que, sozinho, mantém a barra horizontal).
            super().clear()
            for entry in list(self._history):
                super().write(self._render(entry), scroll_end=False)
        finally:
            self._rebuilding = False
        if at_bottom:
            self.scroll_end(animate=False)
        else:
            self.scroll_to(y=offset_y, animate=False)

    def _render(self, entry: Any) -> Any:
        if isinstance(entry, str):
            try:
                text = Text.from_markup(entry) if self.markup else Text(entry)
            except MarkupError:
                text = Text(entry)
            if self.highlight:
                text = self.highlighter(text)
        elif isinstance(entry, Text):
            text = entry.copy()
        else:
            return entry

        if self._search_pattern:
            text.highlight_regex(
                re.compile(re.escape(self._search_pattern), re.IGNORECASE),
                style=self.HIGHLIGHT_STYLE,
            )
        return text

    # ------------------------------------------------------------------ wrap
    @property
    def wrapping(self) -> bool:
        return bool(self.wrap)

    def toggle_wrap(self) -> bool:
        """Liga/desliga a quebra de linha e devolve o novo estado."""
        self.wrap = not self.wrap
        self.rebuild(immediate=True)
        return bool(self.wrap)

    # ------------------------------------------------------------------ busca
    def set_search(self, pattern: str) -> int:
        """Aplica (ou remove) o destaque de busca. Devolve o nº de ocorrências."""
        pattern = pattern.strip()
        if pattern == self._search_pattern:
            return self.count_matches(pattern)
        self._search_pattern = pattern
        self._search_pos = 0
        self._rebuild()
        return self.count_matches(pattern)

    @property
    def search_pattern(self) -> str:
        return self._search_pattern

    def count_matches(self, pattern: str | None = None) -> int:
        needle = (self._search_pattern if pattern is None else pattern).casefold()
        if not needle:
            return 0
        return sum(line.text.casefold().count(needle) for line in self.lines)

    def find_next(self, pattern: str | None = None) -> int | None:
        """Rola até a próxima ocorrência e devolve o índice da linha."""
        needle = (self._search_pattern if pattern is None else pattern).casefold()
        total = len(self.lines)
        if not needle or not total:
            return None
        for step in range(total):
            index = (self._search_pos + step) % total
            if needle in self.lines[index].text.casefold():
                self._search_pos = (index + 1) % total
                self.scroll_to(
                    y=max(0, index - self.size.height // 2), animate=False
                )
                return index
        self._search_pos = 0
        return None

    # ------------------------------------------------------------------ scroll
    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        super()._on_mouse_scroll_up(event)
        if not self.is_vertical_scroll_end:
            self.auto_scroll = False

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        super()._on_mouse_scroll_down(event)
        if self.is_vertical_scroll_end:
            self.auto_scroll = True

    def jump_to_end(self) -> None:
        """Volta para o fim do log e retoma o auto-scroll."""
        self.auto_scroll = True
        self.scroll_end(animate=False)

    # ------------------------------------------------------------------ export
    def export_text(self) -> str:
        """Histórico em texto puro (sem marcação Rich)."""
        chunks: list[str] = []
        for entry in self._history:
            if isinstance(entry, str):
                chunks.append(strip_markup(entry))
            elif isinstance(entry, Text):
                chunks.append(entry.plain)
            else:
                chunks.append(Text.from_markup(str(entry)).plain)
        return "\n".join(chunks)
