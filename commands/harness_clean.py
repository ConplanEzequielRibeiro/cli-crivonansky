"""Comando /harness-clean — limpeza de artefatos e execuções."""

from core.command import Command

from .complements.harness_core import cli


class HarnessCleanCommand(Command):
    name = "harness-clean"
    description = "Harness · limpeza (artefatos e execuções antigas)"
    pack = "harness_clean"
    help_text = """Uso:
  /harness-clean artifacts [--scope skeleton,db,links,docs,legacy-code] [--param dry_run=true]
  /harness-clean runs [--days 30] [--keep 100] [--param dry_run=true]
  /harness-clean run clean:artifacts|clean:runs [params]
  /harness-clean tasks | runs [--last N] | prompt | env:check
  (opção global: --config CAMINHO)"""

    def execute(self, args):
        return cli.execute(self.pack, list(args))
