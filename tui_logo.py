"""Arte em caracteres exibida como texto inicial na TUI.

A palavra ``CLI CRIVONANSKY`` usa uma versão estilizada (fonte figlet
"future"), com o boneco stick — e seu cigarro — escorado na letra inicial.
"""

from rich.text import Text

# Palavra estilizada (41 colunas). Mantida em caracteres de desenho de caixa,
# que são largura 1 e alinham igual em terminais diferentes.
_WORD = [
    "┏━╸╻  ╻   ┏━╸┏━┓╻╻ ╻┏━┓┏┓╻┏━┓┏┓╻┏━┓╻┏ ╻ ╻",
    "┃  ┃  ┃   ┃  ┣┳┛┃┃┏┛┃ ┃┃┗┫┣━┫┃┗┫┗━┓┣┻┓┗┳┛",
    "┗━╸┗━╸╹   ┗━╸╹┗╸╹┗┛ ┗━┛╹ ╹╹ ╹╹ ╹┗━┛╹ ╹ ╹",
]

# Boneco com traços de desenho de caixa (● ╱ ╲ ┃ ┻) e o cigarro na mão
# esquerda, para ficar menos esparso e combinar com a palavra estilizada.
ART = "\n".join(
    [
        "      ●",
        "   🚬╱┃╲" + _WORD[0],
        "      ┻ " + _WORD[1],
        "     ╱ ╲" + _WORD[2],
    ]
)

# Versão para terminais estreitos: boneco pequeno + título em texto puro.
COMPACT_ART = "\n".join(
    [
        "      ●",
        "   🚬╱┃╲",
        "      ┻",
        "     ╱ ╲",
    ]
)

TITLE = "CLI CRIVONANSKY"
WELCOME = "digite /help para começar"


def banner(compact: bool = False) -> Text:
    """Arte + dica, para ser escrita no log ao iniciar."""
    text = Text()
    text.append(COMPACT_ART if compact else ART, style="bold cyan")
    text.append("\n\n")
    if compact:
        text.append(f" {TITLE}\n", style="bold")
    text.append(f" {WELCOME}", style="dim")
    return text
