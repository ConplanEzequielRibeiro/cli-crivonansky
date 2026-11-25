import os
import shlex


def _strip_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def _split_windows(input_line: str) -> list[str]:
    """Split sem ``posix``: preserva barras invertidas de caminhos do Windows."""
    lexer = shlex.shlex(input_line, posix=False)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return [_strip_quotes(token) for token in lexer]


class CommandParser:
    @staticmethod
    def parse(input_line: str):
        line = (input_line or "").strip()
        parts = _split_windows(line) if os.name == "nt" else shlex.split(line)

        if not parts:
            return None, []

        if parts[0].startswith("/"):
            return parts[0], parts[1:]

        return parts[0], parts[1:]
