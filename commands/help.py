import time

from core import result_block
from core.command import Command


class HelpCommand(Command):
    name = "help"
    description = "Lista comandos disponíveis"
    help_text = (
        "Uso: /help\n"
        "Lista todos os comandos registrados, com o texto de ajuda de cada plugin, no\n"
        "bloco crivonansky-result (copiado também para o clipboard).\n"
        "Use /<comando> --help para a ajuda específica de um comando."
    )

    def execute(self, args):
        start = time.time()

        commands = self.context.registry.all()
        details = [f"Comandos disponíveis ({len(commands)}):", ""]
        for _name, cmd in commands.items():
            details.append(cmd.get_usage())
            details.append("")

        block, _truncated = result_block.format_result(
            result_block.new_id(),
            "help",
            "success",
            0,
            int((time.time() - start) * 1000),
            f"ajuda de {len(commands)} comando(s)",
            "\n".join(details).rstrip() + "\n",
            [],
            result_block.MAX_CHARS,
        )
        copied = result_block.copy_to_clipboard(block)

        print(block)
        return True, {"count": len(commands), "clipboard": copied}
