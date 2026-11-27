"""Comando /harness-state — continuidade de tarefa entre conversas."""

from core.command import Command

from .complements.harness_core import cli


class HarnessStateCommand(Command):
    name = "harness-state"
    description = "Harness · estado (retomar tarefa em outra conversa)"
    pack = "harness_state"
    help_text = """Uso:
  /harness-state save --clip | --file F | --content TEXTO
  /harness-state list
  /harness-state load [--last | NOME]
  /harness-state run state:save|state:load|state:list [params]
  /harness-state exec --clip | --file F | --stdin
  /harness-state tasks | runs [--last N] | prompt | env:check
  (opção global: --config CAMINHO)"""

    def execute(self, args):
        return cli.execute(self.pack, list(args))
