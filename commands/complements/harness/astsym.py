"""Extração de símbolos (funções, métodos, classes) do código legado.

Usa ``ast-grep`` (pacote ``ast-grep-py``, wheel nativa) quando disponível e cai
para regex + casamento de chaves quando não. O esqueleto (`code:skeleton`) e o
`db:links` compartilham este módulo, então o campo ``symbol`` dos vínculos não
depende de nenhum grafo externo.
"""

import os
import re

# Extensão -> linguagem do ast-grep.
_LANGUAGES = {
    ".php": "php",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".py": "python",
}

# Kinds de definição por linguagem (ast-grep) -> rótulo usado no harness.
_DEFINITION_KINDS = {
    "php": {
        "function_definition": "function",
        "method_declaration": "method",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "trait_declaration": "trait",
    },
    "javascript": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
    },
    "typescript": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
    },
    "tsx": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
    },
    "python": {
        "function_definition": "function",
        "class_definition": "class",
    },
}

# Fallback (sem ast-grep): (regex, grupo com o nome, rótulo).
_FALLBACK = {
    ".php": [
        (re.compile(r"\bfunction\s+(\w+)\s*\(", re.I), 1, "function"),
        (re.compile(r"\b(?:class|interface|trait)\s+(\w+)", re.I), 1, "class"),
    ],
    ".js": [
        (re.compile(r"\bfunction\s+(\w+)\s*\(", re.I), 1, "function"),
        (re.compile(r"\bclass\s+(\w+)", re.I), 1, "class"),
        (
            re.compile(
                r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function|\()", re.I
            ),
            1,
            "function",
        ),
    ],
    ".ts": [
        (re.compile(r"\bfunction\s+(\w+)\s*[(<]", re.I), 1, "function"),
        (re.compile(r"\bclass\s+(\w+)", re.I), 1, "class"),
        (
            re.compile(
                r"\b(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:function|\()",
                re.I,
            ),
            1,
            "function",
        ),
    ],
    ".py": [
        (re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.M), 1, "function"),
        (re.compile(r"^\s*class\s+(\w+)", re.M), 1, "class"),
    ],
}
_FALLBACK[".jsx"] = _FALLBACK[".js"]
_FALLBACK[".mjs"] = _FALLBACK[".js"]
_FALLBACK[".cjs"] = _FALLBACK[".js"]
_FALLBACK[".tsx"] = _FALLBACK[".ts"]


def ast_grep():
    """Devolve o módulo ``ast_grep_py`` ou ``None`` se não estiver instalado."""
    try:
        import ast_grep_py  # noqa: PLC0415 - dependência opcional
    except Exception:  # noqa: BLE001 - wheel ausente/quebrada não deve derrubar
        return None
    return ast_grep_py


def available() -> bool:
    return ast_grep() is not None


def language_for(path: str) -> str | None:
    return _LANGUAGES.get(os.path.splitext(path)[1].lower())


def definitions(text: str, path: str) -> list[dict]:
    """Lista ``{name, line, end, kind}`` das definições do arquivo (1-based)."""
    extension = os.path.splitext(path)[1].lower()
    language = _LANGUAGES.get(extension)
    if language:
        found = _definitions_ast(text, language)
        if found is not None:
            return found
    return _definitions_regex(text, extension)


# ---------------------------------------------------------------------------
# ast-grep
# ---------------------------------------------------------------------------
def _definitions_ast(text: str, language: str) -> list[dict] | None:
    module = ast_grep()
    if module is None:
        return None

    try:
        root = module.SgRoot(text, language).root()
    except Exception:  # noqa: BLE001 - parser não suporta a variação
        return None

    kinds = _DEFINITION_KINDS.get(language) or {}
    found: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for kind, label in kinds.items():
        try:
            nodes = root.find_all(kind=kind)
        except Exception:  # noqa: BLE001
            continue
        for node in nodes:
            name_node = node.field("name")
            name = name_node.text() if name_node is not None else ""
            if not name:
                continue
            start = node.range().start.line + 1
            end = node.range().end.line + 1
            key = (name, start)
            if key in seen:
                continue
            seen.add(key)
            found.append({"name": name, "line": start, "end": end, "kind": label})

    # JS/TS: `const foo = () => {}` / `const foo = function () {}`.
    if language in ("javascript", "typescript", "tsx"):
        try:
            declarators = root.find_all(kind="variable_declarator")
        except Exception:  # noqa: BLE001
            declarators = []
        for node in declarators:
            value = node.field("value")
            value_text = value.text() if value is not None else node.text()
            if "=>" not in value_text and "function" not in value_text:
                continue
            name_node = node.field("name")
            name = name_node.text() if name_node is not None else ""
            if not name:
                continue
            start = node.range().start.line + 1
            end = node.range().end.line + 1
            if (name, start) in seen:
                continue
            seen.add((name, start))
            found.append({"name": name, "line": start, "end": end, "kind": "function"})

    found.sort(key=lambda item: (item["line"], item["name"]))
    return found


# ---------------------------------------------------------------------------
# Fallback: regex + fim de bloco
# ---------------------------------------------------------------------------
def _definitions_regex(text: str, extension: str) -> list[dict]:
    patterns = _FALLBACK.get(extension) or []
    found: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for pattern, group, label in patterns:
        for match in pattern.finditer(text):
            name = match.group(group)
            if not name:
                continue
            line = text.count("\n", 0, match.start()) + 1
            key = (name, line)
            if key in seen:
                continue
            seen.add(key)

            if extension == ".py":
                end = python_block_end(text, line)
            else:
                end = brace_block_end(text, line)
            found.append({"name": name, "line": line, "end": end or line, "kind": label})

    found.sort(key=lambda item: (item["line"], item["name"]))
    return found


def brace_block_end(text: str, start_line: int, line_starts: list[int] | None = None) -> int | None:
    """Linha de fechamento de um bloco ``{...}`` (PHP/JS/TS).

    Ignora chaves dentro de strings e comentários. Devolve ``None`` quando o
    bloco não fecha no arquivo.
    """
    if start_line < 1:
        return None

    if line_starts is not None:
        if start_line > len(line_starts):
            return None
        offset = line_starts[start_line - 1]
    else:
        offset = 0
        for _ in range(start_line - 1):
            newline = text.find("\n", offset)
            if newline == -1:
                return None
            offset = newline + 1

    state = "code"
    depth = 0
    opened = False
    line_no = start_line
    index = offset

    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""

        if state == "code":
            if char == "'":
                state = "single"
            elif char == '"':
                state = "double"
            elif char == "/" and nxt == "/":
                state = "line_comment"
                index += 1
            elif char == "#":
                state = "line_comment"
            elif char == "/" and nxt == "*":
                state = "block_comment"
                index += 1
            elif char == "{":
                depth += 1
                opened = True
            elif char == "}":
                if opened:
                    depth -= 1
                    if depth == 0:
                        return line_no
            elif char == "\n":
                line_no += 1
        elif state in ("single", "double"):
            quote = "'" if state == "single" else '"'
            if char == "\\":
                index += 1
            elif char == quote:
                state = "code"
            elif char == "\n":
                line_no += 1
        elif state == "line_comment":
            if char == "\n":
                state = "code"
                line_no += 1
        elif state == "block_comment":
            if char == "*" and nxt == "/":
                state = "code"
                index += 1
            elif char == "\n":
                line_no += 1

        index += 1

    return None


def python_block_end(text: str, start_line: int) -> int | None:
    """Última linha do corpo de um ``def``/``class`` pela indentação."""
    lines = text.splitlines()
    if start_line < 1 or start_line > len(lines):
        return None

    header = lines[start_line - 1]
    base = len(header) - len(header.lstrip())
    end = start_line

    for number in range(start_line + 1, len(lines) + 1):
        line = lines[number - 1]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base:
            break
        end = number

    return end
