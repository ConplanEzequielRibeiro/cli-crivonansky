"""Comando /harness-exec — execução (shell, Python, Docker, git, logs)."""

from core.command import Command

from .complements.harness_core import cli


class HarnessExecCommand(Command):
    name = "harness-exec"
    description = "Harness · execução (shell, Python, Docker, git, logs)"
    pack = "harness_exec"
    help_text = """Uso:
  /harness-exec run shell:run --command "..." [--yes]
  /harness-exec run py:run --script arquivo.py | --module pacote [--args "..."]
  /harness-exec run docker:exec --container NOME --command "..."
  /harness-exec run logs:tail --container NOME [--lines N]
  /harness-exec run git:run --args "status" [--repo CAMINHO]
  /harness-exec exec --clip | --file F | --stdin [--yes] [--dry-run] [--no-clipboard]
  /harness-exec tasks | runs [--last N] | prompt | env:check
  (opção global: --config CAMINHO)"""

    def execute(self, args):
        return cli.execute(self.pack, list(args))
