"""Extração de símbolos (funções, métodos, classes) do código legado.

Usa ``ast-grep`` (pacote ``ast-grep-py``, wheel nativa) quando disponível e cai
para regex + casamento de chaves/indentação quando não. A lista de linguagens e
kinds vem do perfil de stack (`profiles.py`), então o mesmo código atende
PHP, JS/TS, Python, Java, C#, Ruby, Go, Kotlin, Scala, C/C++ e Elixir.
"""

import os
import re

from .profiles import DEFINITION_KINDS, EXTENSION_LANGUAGES, IMPORT_PATTERNS

# Extensões cujo bloco termina por indentação (não por chaves).
_INDENT_EXTENSIONS = {".py", ".rb", ".erb", ".ex", ".exs"}

# Filhos usados como nome quando o nó não expõe o campo `name` (Kotlin).
_NAME_CHILD_KINDS = {
    "identifier",
    "type_identifier",
    "simple_identifier",
    "field_identifier",
    "property_identifier",
    "constant",
    "name",
}

# Fallback (sem ast-grep): (regex, grupo com o nome, rótulo).
_FALLBACK: dict[str, list[tuple[re.Pattern, int, str]]] = {
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
    ".java": [
        (
            re.compile(r"^\s*(?:public|private|protected)?\s*(?:class|interface|enum|record)\s+(\w+)", re.M),
            1,
            "class",
        ),
        (
            re.compile(
                r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)*"
                r"[\w<>\[\],.?]+\s+(\w+)\s*\([^;{}]*\)\s*(?:throws\s+[\w, .]+)?\{",
                re.M,
            ),
            1,
            "method",
        ),
    ],
    ".cs": [
        (
            re.compile(
                r"^\s*(?:(?:public|private|protected|internal|static|sealed|abstract|partial)\s+)*"
                r"(?:class|interface|struct|record|enum)\s+(\w+)",
                re.M,
            ),
            1,
            "class",
        ),
        (
            re.compile(
                r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|async|sealed)\s+)+"
                r"[\w<>\[\],.?]+\s+(\w+)\s*\([^;{}]*\)\s*\{",
                re.M,
            ),
            1,
            "method",
        ),
    ],
    ".rb": [
        (
            re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)", re.M),
            1,
            "method",
        ),
        (re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*(?:::\w+)*)", re.M), 1, "class"),
    ],
    ".go": [
        (
            re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(", re.M),
            1,
            "function",
        ),
        (
            re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface)", re.M),
            1,
            "type",
        ),
    ],
    ".kt": [
        (
            re.compile(r"^\s*fun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\(", re.M),
            1,
            "function",
        ),
        (
            re.compile(r"^\s*(?:class|interface|object)\s+([A-Za-z_]\w*)", re.M),
            1,
            "class",
        ),
    ],
    ".scala": [
        (re.compile(r"^\s*def\s+([A-Za-z_]\w*)", re.M), 1, "function"),
        (
            re.compile(r"^\s*(?:class|object|trait)\s+([A-Za-z_]\w*)", re.M),
            1,
            "class",
        ),
    ],
    ".c": [
        (
            re.compile(
                r"^[^#\n;{}]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{", re.M
            ),
            1,
            "function",
        ),
        (re.compile(r"\b(?:struct|enum)\s+(\w+)\s*\{", re.M), 1, "struct"),
    ],
    ".cpp": [
        (
            re.compile(r"\b(?:class|struct)\s+(\w+)\s*[:{]?", re.M),
            1,
            "class",
        ),
        (
            re.compile(
                r"^[^#\n;{}]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{", re.M
            ),
            1,
            "function",
        ),
        (re.compile(r"\bnamespace\s+(\w+)", re.M), 1, "namespace"),
    ],
    ".ex": [
        (re.compile(r"^\s*defmodule\s+([\w.]+)", re.M), 1, "module"),
        (re.compile(r"^\s*defp?\s+([a-z_]\w*[?!]?)", re.M), 1, "function"),
    ],
}
_FALLBACK[".jsx"] = _FALLBACK[".js"]
_FALLBACK[".mjs"] = _FALLBACK[".js"]
_FALLBACK[".cjs"] = _FALLBACK[".js"]
_FALLBACK[".tsx"] = _FALLBACK[".ts"]
_FALLBACK[".jsp"] = _FALLBACK[".java"]
_FALLBACK[".erb"] = _FALLBACK[".rb"]
_FALLBACK[".kts"] = _FALLBACK[".kt"]
_FALLBACK[".h"] = _FALLBACK[".c"]
_FALLBACK[".cc"] = _FALLBACK[".cpp"]
_FALLBACK[".hpp"] = _FALLBACK[".cpp"]

# Palavras que o regex de função (C-like) pode capturar por engano.
_NOT_NAMES = {"if", "for", "while", "switch", "catch", "return", "else", "do", "try"}


# ---------------------------------------------------------------------------
# PHP com HTML misto: mascarar o HTML antes de parsear
# ---------------------------------------------------------------------------
# Um arquivo PHP alterna entre HTML e blocos ``<?php … ?>``. O scanner externo
# do tree-sitter se confunde com tags PHP dentro de strings/comentários do HTML
# (``<script>var x = '<?php … ?>'</script>``, ``<!-- <?php … ?> -->``) e passa a
# tratar o resto do arquivo como texto — os símbolos (e as SQLs associadas a
# eles) depois do HTML somem. Mascarar o HTML por espaços, preservando ``\n`` e
# ``\r``, entrega ao parser apenas o código PHP com os mesmos números de linha.
_HEREDOC_START_RE = re.compile(r"<<<[ \t]*(['\"]?)([A-Za-z_]\w*)\1[ \t]*\r?\n")
_XML_DECL_RE = re.compile(r"<\?xml(?:\s|\?|-|$)", re.I)


def _blank(chars: list[str], start: int, end: int) -> None:
    for index in range(max(start, 0), min(end, len(chars))):
        if chars[index] not in "\r\n":
            chars[index] = " "


def _skip_quoted(text: str, index: int, limit: int, quote: str) -> int:
    while index < limit:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return limit


def _skip_line_comment(text: str, index: int, limit: int) -> int:
    # Em PHP, ``?>`` também encerra comentários de uma linha.
    while index < limit:
        char = text[index]
        if char == "\n":
            return index + 1
        if char == "?" and text.startswith("?>", index):
            return index
        index += 1
    return limit


def _skip_block_comment(text: str, index: int, limit: int) -> int:
    end = text.find("*/", index)
    return limit if end == -1 else end + 2


def _skip_heredoc(text: str, index: int, limit: int) -> int | None:
    """Fim do heredoc/nowdoc; ``None`` se ``<<<`` não abrir um heredoc."""
    match = _HEREDOC_START_RE.match(text, index)
    if match is None:
        return None
    closing = re.compile(
        rf"^[ \t]*{re.escape(match.group(2))}(?![A-Za-z0-9_])", re.MULTILINE
    )
    found = closing.search(text, match.end(), limit)
    return limit if found is None else found.start()


def _php_block_end(text: str, index: int, limit: int) -> int:
    """Índice logo após o ``?>`` que fecha o bloco PHP (ou ``limit``)."""
    while index < limit:
        char = text[index]
        nxt = text[index + 1] if index + 1 < limit else ""
        if char == "?" and nxt == ">":
            return index + 2
        if char in ("'", '"', "`"):
            index = _skip_quoted(text, index + 1, limit, char)
        elif char == "/" and nxt == "/":
            index = _skip_line_comment(text, index + 2, limit)
        elif char == "#" and nxt != "[":
            index = _skip_line_comment(text, index + 1, limit)
        elif char == "/" and nxt == "*":
            index = _skip_block_comment(text, index + 2, limit)
        elif char == "<" and text.startswith("<<<", index):
            heredoc_end = _skip_heredoc(text, index, limit)
            index = index + 1 if heredoc_end is None else heredoc_end
        else:
            index += 1
    return limit


def php_code_only(text: str) -> str:
    """Zera o HTML de um arquivo PHP misto, mantendo offsets e números de linha.

    Devolve o próprio ``text`` quando não há nenhuma tag PHP (nada a mascarar).
    """
    limit = len(text)
    chars = list(text)
    index = 0
    opened = False
    while index < limit:
        start = text.find("<?", index)
        if start == -1:
            _blank(chars, index, limit)
            break
        if _XML_DECL_RE.match(text, start):  # declaração XML no HTML, não é PHP
            _blank(chars, index, start + 2)
            index = start + 2
            continue
        opened = True
        _blank(chars, index, start)
        index = _php_block_end(text, start + 2, limit)
    return "".join(chars) if opened else text


def ast_grep():
    """Devolve o módulo ``ast_grep_py`` ou ``None`` se não estiver instalado."""
    try:
        import ast_grep_py  # noqa: PLC0415 - dependência opcional
    except Exception:  # noqa: BLE001 - wheel ausente/quebrada não deve derrubar
        return None
    return ast_grep_py


def available() -> bool:
    return ast_grep() is not None


def language_for(path: str, languages: dict[str, str] | None = None) -> str | None:
    mapping = languages if languages is not None else EXTENSION_LANGUAGES
    return mapping.get(os.path.splitext(path)[1].lower())


def definitions(
    text: str,
    path: str,
    languages: dict[str, str] | None = None,
    definition_kinds: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Lista ``{name, line, end, kind}`` das definições do arquivo (1-based)."""
    extension = os.path.splitext(path)[1].lower()
    mapping = languages if languages is not None else EXTENSION_LANGUAGES
    kinds_map = definition_kinds if definition_kinds is not None else DEFINITION_KINDS

    language = mapping.get(extension)
    # PHP/HTML misto: o parser puro se perde no HTML (tags PHP dentro de strings
    # de `<script>`, comentários HTML etc.) e ignora o código que vem depois.
    source = php_code_only(text) if language == "php" else text
    if language:
        found = _definitions_ast(source, language, kinds_map.get(language) or {})
        if found is not None:
            return found
    return _definitions_regex(source, extension, language)


def extract_imports(
    text: str,
    path: str,
    import_patterns: dict[str, str] | None = None,
    limit: int = 40,
) -> list[str]:
    """Linhas de import/include do arquivo, conforme o padrão da linguagem."""
    language = language_for(path)
    patterns = import_patterns if import_patterns is not None else IMPORT_PATTERNS
    pattern = patterns.get(language or "")
    if not pattern:
        return []

    if language == "php":
        text = php_code_only(text)

    values: list[str] = []
    for match in re.finditer(pattern, text, re.MULTILINE):
        line = match.group(0).strip()
        if line and line not in values:
            values.append(line[:160])
        if len(values) >= limit:
            break
    return values


# ---------------------------------------------------------------------------
# ast-grep
# ---------------------------------------------------------------------------
# Linguagens que podem chegar ao parser. Fora daqui (ex.: `c_sharp`, valor
# cru do YAML) o ast-grep derruba o processo com PanicException.
_SUPPORTED_LANGUAGES = frozenset(DEFINITION_KINDS)


def _definitions_ast(text: str, language: str, kinds: dict[str, str]) -> list[dict] | None:
    """Definições via AST. ``None`` significa "use o fallback por regex"."""
    if not kinds:
        return None

    module = ast_grep()
    if module is None:
        return None

    # Allowlist: linguagem fora do mapa (ou inválida) nunca vai ao parser.
    if language not in _SUPPORTED_LANGUAGES:
        return None

    try:
        root = module.SgRoot(text, language).root()
    except BaseException:  # noqa: BLE001 - PyO3 PanicException não herda Exception
        return None

    found: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for kind, label in kinds.items():
        try:
            nodes = root.find_all(kind=kind)
        except Exception:  # noqa: BLE001
            continue
        for node in nodes:
            name = _node_name(node, language)
            if not name:
                continue
            start = node.range().start.line + 1
            end = node.range().end.line + 1
            key = (name, start)
            if key in seen:
                continue
            seen.add(key)
            found.append({"name": name, "line": start, "end": end, "kind": label})

    # C/C++: declarações (`void bar();`) não são `function_definition`.
    if language in ("c", "cpp"):
        try:
            declarators = root.find_all(kind="function_declarator")
        except Exception:  # noqa: BLE001
            declarators = []
        for node in declarators:
            try:
                if any(parent.kind() == "function_definition" for parent in node.ancestors()):
                    continue
            except Exception:  # noqa: BLE001
                pass
            inner = node.field("declarator")
            text = inner.text() if inner is not None else node.text()
            name = text.split("(")[0].strip().split("::")[-1].strip()
            if not name:
                continue
            start = node.range().start.line + 1
            if (name, start) in seen:
                continue
            seen.add((name, start))
            found.append(
                {
                    "name": name,
                    "line": start,
                    "end": node.range().end.line + 1,
                    "kind": "function",
                }
            )

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
            name = _node_name(node, language)
            if not name:
                continue
            start = node.range().start.line + 1
            if (name, start) in seen:
                continue
            seen.add((name, start))
            found.append(
                {
                    "name": name,
                    "line": start,
                    "end": node.range().end.line + 1,
                    "kind": "function",
                }
            )

    found.sort(key=lambda item: (item["line"], item["name"]))
    return found


def _node_name(node, language: str) -> str:
    """Nome da definição, cobrindo nós sem campo ``name`` (Kotlin, C/C++)."""
    value = node.field("name")
    if value is not None:
        text = value.text().strip()
        if text:
            return text

    if language in ("c", "cpp") and node.kind() == "function_definition":
        for child in node.named_children():
            if child.kind() != "function_declarator":
                continue
            inner = child.field("declarator")
            text = inner.text() if inner is not None else child.text()
            name = text.split("(")[0].strip().split("::")[-1].strip()
            if name:
                return name
        declarator = node.field("declarator")
        if declarator is not None:
            return declarator.text().split("(")[0].strip().split("::")[-1].strip()

    for child in node.named_children():
        if child.kind() in _NAME_CHILD_KINDS:
            return child.text().strip()
    return ""


# ---------------------------------------------------------------------------
# Fallback: regex + fim de bloco
# ---------------------------------------------------------------------------
def _definitions_regex(text: str, extension: str, language: str | None = None) -> list[dict]:
    patterns = _FALLBACK.get(extension)
    if patterns is None and language == "php":  # .phtml, .inc, .php5 ...
        patterns = _FALLBACK.get(".php") or []
    patterns = patterns or []
    found: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for pattern, group, label in patterns:
        for match in pattern.finditer(text):
            name = match.group(group)
            if not name or name.lower() in _NOT_NAMES:
                continue
            line = text.count("\n", 0, match.start()) + 1
            key = (name, line)
            if key in seen:
                continue
            seen.add(key)

            if extension in _INDENT_EXTENSIONS:
                end = indent_block_end(text, line)
            else:
                end = brace_block_end(text, line)
            found.append({"name": name, "line": line, "end": end or line, "kind": label})

    found.sort(key=lambda item: (item["line"], item["name"]))
    return found


def brace_block_end(text: str, start_line: int, line_starts: list[int] | None = None) -> int | None:
    """Linha de fechamento de um bloco ``{...}`` (PHP/JS/Java/C#/...).

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


def indent_block_end(text: str, start_line: int) -> int | None:
    """Última linha do corpo de um bloco por indentação (Python/Ruby/Elixir)."""
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
