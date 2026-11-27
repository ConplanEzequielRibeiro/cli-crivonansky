"""Comando /harness-validate — pipelines test:run, verify e lint."""

from core.command import Command

from .complements.harness_core import cli


class HarnessValidateCommand(Command):
    name = "harness-validate"
    description = "Harness · validação (test:run, verify, lint)"
    pack = "harness_validate"
    help_text = """Uso:
  /harness-validate run test:run [--filter F]
  /harness-validate run verify
  /harness-validate run lint
  /harness-validate exec --clip | --file F | --stdin [--dry-run]
  /harness-validate tasks | runs [--last N] | prompt | env:check
  (opção global: --config CAMINHO)"""

    def execute(self, args):
        return cli.execute(self.pack, list(args))
