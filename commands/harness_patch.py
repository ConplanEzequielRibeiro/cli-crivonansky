"""Comando /harness-patch — aplicação de diff com encoding/CRLF/BOM."""

from core.command import Command

from .complements.harness_core import cli


class HarnessPatchCommand(Command):
    name = "harness-patch"
    description = "Harness · patch (diff com encoding/CRLF/BOM)"
    pack = "harness_patch"
    help_text = """Uso:
  /harness-patch run patch:apply --file F --branch B [--verify] [--yes]
  /harness-patch apply --file F --branch B [--yes]
  /harness-patch exec --clip | --file F | --stdin [--yes] [--dry-run]
  /harness-patch tasks | runs [--last N] | prompt | env:check
  (opção global: --config CAMINHO)"""

    def execute(self, args):
        return cli.execute(self.pack, list(args))
