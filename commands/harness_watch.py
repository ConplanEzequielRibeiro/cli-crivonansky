"""Comando /harness-watch — monitores de clipboard e downloads."""

from core.command import Command

from .complements.harness_core import cli


class HarnessWatchCommand(Command):
    name = "harness-watch"
    description = "Harness · monitores (clipboard e downloads)"
    pack = "harness_watch"
    help_text = """Uso:
  /harness-watch clip [--interval_ms N] [--stop] [--max_cycles N]
  /harness-watch downloads [--path P] [--branch B] [--stop] [--include_existing]
  /harness-watch run watch:clip|watch:downloads [params]
  /harness-watch tasks | runs [--last N] | prompt | env:check
  (opção global: --config CAMINHO)"""

    def execute(self, args):
        return cli.execute(self.pack, list(args))
