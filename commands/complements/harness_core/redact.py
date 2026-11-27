"""Sanitização de saída (LGPD): dados pessoais e segredos não vão para o chat.

Tudo o que o harness devolve ao LLM (clipboard, terminal, ``result.md``) passa
por aqui, conforme ``policy.redact`` no ``harness.yaml``:

.. code-block:: yaml

    policy:
      redact:
        enabled: true                       # padrão: ligado
        patterns: [cpf, cnpj, email, telefone]
        columns: ["*.cpf", "*.nome", "tb_funcionarios.*"]
        secrets: [chave_acesso]             # nomes extras de variáveis secretas
        apply_to: [exec, ask, context:pack]
        keep_raw_log: false                 # true grava o full.log sem máscara

``apply_to``: ``exec`` cobre toda tarefa executada pelo engine (``exec`` e
``run``); ``context:pack`` só essa tarefa; ``ask`` o ``harness ask``.

Os detectores de CPF/CNPJ sem pontuação só mascaram números com dígitos
verificadores válidos, para não esconder identificadores comuns.
"""

import fnmatch
import re
from dataclasses import dataclass

DEFAULT_PATTERNS = ("cpf", "cnpj", "email", "telefone")
DEFAULT_APPLY_TO = ("exec", "ask", "context:pack")

# Nomes de variáveis/chaves tratados como segredo (regex, sem anchors).
DEFAULT_SECRET_NAMES = (
    "pass(?:word)?",
    "senha",
    "pwd",
    "passwd",
    "secret",
    "token",
    "api[_-]?key",
    "private[_-]?key",
    "chave[_-]?secreta",
)

MASK_COLUMN = "[MASCARADO]"
MASK_SECRET = "***"


@dataclass
class RedactPolicy:
    enabled: bool = True
    patterns: tuple = DEFAULT_PATTERNS
    columns: tuple = ()
    secrets: tuple = ()
    apply_to: tuple = DEFAULT_APPLY_TO
    keep_raw_log: bool = False


def _as_tuple(value, default=()) -> tuple:
    if value is None:
        return tuple(default)
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return tuple(str(item) for item in value)


def get_policy(config: dict | None) -> RedactPolicy:
    node = ((config or {}).get("policy") or {}).get("redact")
    if node is None:
        return RedactPolicy()
    if isinstance(node, bool):
        return RedactPolicy(enabled=node)
    if not isinstance(node, dict):
        return RedactPolicy()

    return RedactPolicy(
        enabled=bool(node.get("enabled", True)),
        patterns=tuple(
            item.lower() for item in _as_tuple(node.get("patterns"), DEFAULT_PATTERNS)
        ),
        columns=_as_tuple(node.get("columns")),
        secrets=_as_tuple(node.get("secrets")),
        apply_to=_as_tuple(node.get("apply_to"), DEFAULT_APPLY_TO),
        keep_raw_log=bool(node.get("keep_raw_log", False)),
    )


def applies(policy: RedactPolicy, channel: str) -> bool:
    return policy.enabled and channel in policy.apply_to


# ---------------------------------------------------------------------------
# Dados pessoais
# ---------------------------------------------------------------------------
_CPF_FORMATTED = re.compile(r"(?<![\d.])\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_CNPJ_FORMATTED = re.compile(r"(?<![\d.])\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)")
_CPF_RAW = re.compile(r"(?<![\d.])\d{11}(?![\d])")
_CNPJ_RAW = re.compile(r"(?<![\d.])\d{14}(?![\d])")
_EMAIL = re.compile(
    r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"
)
# Telefone só com formatação (hífen ou DDD entre parênteses), para não esconder
# números soltos como ids e timestamps.
_PHONE_HYPHEN = re.compile(
    r"(?<![\d-])(?:\+55[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?)?9?\d{4}-\d{4}(?![\d-])"
)
_PHONE_PAREN = re.compile(r"(?<!\d)\(\d{2}\)\s?9?\d{4}\s?\d{4}(?!\d)")


def _valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(digits[i]) * (size + 1 - i) for i in range(size))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return False
    return True


def _valid_cnpj(digits: str) -> bool:
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    for size in (12, 13):
        weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        if size == 13:
            weights = [6] + weights
        total = sum(int(digits[i]) * weights[i] for i in range(size))
        check = total % 11
        check = 0 if check < 2 else 11 - check
        if check != int(digits[size]):
            return False
    return True


def _sub(pattern, label: str, text: str, stats: dict, validator=None) -> str:
    def repl(match):
        value = match.group(0)
        if validator is not None and not validator(re.sub(r"\D", "", value)):
            return value
        stats[label] = stats.get(label, 0) + 1
        return f"[{label.upper()}]"

    return pattern.sub(repl, text)


def redact_personal(text: str, patterns, stats: dict) -> str:
    wanted = set(patterns)
    # CNPJ antes de CPF: 14 dígitos contêm sequências de 11.
    if "cnpj" in wanted:
        text = _sub(_CNPJ_FORMATTED, "cnpj", text, stats)
        text = _sub(_CNPJ_RAW, "cnpj", text, stats, _valid_cnpj)
    if "cpf" in wanted:
        text = _sub(_CPF_FORMATTED, "cpf", text, stats)
        text = _sub(_CPF_RAW, "cpf", text, stats, _valid_cpf)
    if "email" in wanted:
        text = _sub(_EMAIL, "email", text, stats)
    if "telefone" in wanted:
        text = _sub(_PHONE_PAREN, "telefone", text, stats)
        text = _sub(_PHONE_HYPHEN, "telefone", text, stats)
    return text


# ---------------------------------------------------------------------------
# Segredos em código/configuração
# ---------------------------------------------------------------------------
_CONNECT_CALL = re.compile(
    r"\b(?:mysql_p?connect|mysqli_(?:real_)?connect|pg_p?connect|oci_(?:p)?connect"
    r"|sqlsrv_connect|new\s+(?:PDO|mysqli))\s*\(",
    re.IGNORECASE,
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_AUTH_HEADER = re.compile(
    r"(?i)(authorization\W{1,4}(?:bearer|basic)\s+)[A-Za-z0-9._\-+/=]{8,}"
)
_IDENTIFIED_BY = re.compile(r"(?i)(identified\s+by\s+)(['\"])(?:\\.|(?!\2)[^\\\n])*\2")
_DSN_PASSWORD = re.compile(r"(?i)(?<![\w$])((?:password|pwd)=)[^;\s'\"&]+")


def _names(extra) -> str:
    return "|".join([*DEFAULT_SECRET_NAMES, *(re.escape(item) for item in extra)])


def _secret_patterns(extra) -> tuple[re.Pattern, re.Pattern, re.Pattern]:
    names = _names(extra)
    quoted = re.compile(
        rf"""(?P<pre>(?:{names})[\w\]\['"]*\s*(?:===?|!==?|=>|=|:)\s*)"""
        rf"""(?P<q>["'])(?:\\.|(?!(?P=q))[^\\\n])*(?P=q)""",
        re.IGNORECASE,
    )
    define = re.compile(
        rf"""(?P<pre>\bdefine\s*\(\s*(?P<k>["'])\w*(?:{names})\w*(?P=k)\s*,\s*)"""
        rf"""(?P<q>["'])(?:\\.|(?!(?P=q))[^\\\n])*(?P=q)""",
        re.IGNORECASE,
    )
    # Estilo .env/ini/yaml: valor sem aspas e sem cara de código.
    bare = re.compile(
        rf"""^(?P<pre>[ \t]*(?:export[ \t]+)?[A-Za-z0-9_.\-]*(?:{names})[A-Za-z0-9_.\-]*"""
        rf"""[ \t]*(?:=|:)[ \t]*)(?P<val>[^\s"'#$\[\{{(;][^\r\n#;()]*)$""",
        re.IGNORECASE | re.MULTILINE,
    )
    return quoted, define, bare


def _split_args(text: str, start: int) -> tuple[list[tuple[int, int]], int] | None:
    """Intervalos dos argumentos de uma chamada (``start`` logo após o ``(``)."""
    depth = 0
    quote = None
    spans: list[tuple[int, int]] = []
    begin = start
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                spans.append((begin, index))
                return spans, index
            depth -= 1
        elif char == "," and depth == 0:
            spans.append((begin, index))
            begin = index + 1
        index += 1
    return None


def _mask_connect_calls(text: str, stats: dict) -> str:
    out: list[str] = []
    cursor = 0
    for match in _CONNECT_CALL.finditer(text):
        if match.start() < cursor:
            continue
        parsed = _split_args(text, match.end())
        if not parsed:
            continue
        spans, close = parsed
        if len(spans) < 3:
            continue
        begin, end = spans[2]
        argument = text[begin:end]
        stripped = argument.strip()
        if len(stripped) >= 2 and stripped[0] in "'\"" and stripped[-1] == stripped[0]:
            if stripped[1:-1] == MASK_SECRET:
                continue
            lead = argument[: len(argument) - len(argument.lstrip())]
            trail = argument[len(argument.rstrip()) :]
            out.append(text[cursor:begin])
            out.append(f'{lead}"{MASK_SECRET}"{trail}')
            cursor = end
            stats["segredo"] = stats.get("segredo", 0) + 1
    out.append(text[cursor:])
    return "".join(out)


def redact_secrets(text: str, extra_names=(), stats: dict | None = None) -> str:
    """Mascara senhas, tokens e chaves em fontes e arquivos de configuração."""
    if not text:
        return text
    stats = stats if stats is not None else {}
    quoted, define, bare = _secret_patterns(tuple(extra_names))

    def count(label="segredo"):
        stats[label] = stats.get(label, 0) + 1

    def keep_pre(match):
        value = match.group(0)[len(match.group("pre")) :]
        if value.strip("'\"") == MASK_SECRET:
            return match.group(0)
        count()
        return f'{match.group("pre")}"{MASK_SECRET}"'

    text = _mask_connect_calls(text, stats)
    text = define.sub(keep_pre, text)
    text = quoted.sub(keep_pre, text)

    def bare_sub(match):
        if match.group("val").strip() == MASK_SECRET:
            return match.group(0)
        count()
        return f'{match.group("pre")}{MASK_SECRET}'

    text = bare.sub(bare_sub, text)

    def ident_sub(match):
        count()
        return f'{match.group(1)}"{MASK_SECRET}"'

    text = _IDENTIFIED_BY.sub(ident_sub, text)

    def dsn_sub(match):
        if match.group(0).endswith(MASK_SECRET):
            return match.group(0)
        count()
        return f"{match.group(1)}{MASK_SECRET}"

    text = _DSN_PASSWORD.sub(dsn_sub, text)

    def auth_sub(match):
        count()
        return f"{match.group(1)}{MASK_SECRET}"

    text = _AUTH_HEADER.sub(auth_sub, text)

    def key_sub(match):
        count()
        # Mantém a contagem de linhas (code:read numera as linhas do arquivo).
        return "[CHAVE PRIVADA]" + "\n" * match.group(0).count("\n")

    return _PRIVATE_KEY.sub(key_sub, text)


# ---------------------------------------------------------------------------
# API de alto nível
# ---------------------------------------------------------------------------
def redact_text(
    text: str,
    policy: RedactPolicy,
    stats: dict | None = None,
) -> tuple[str, dict]:
    """Aplica segredos + dados pessoais. Devolve ``(texto, contadores)``."""
    stats = stats if stats is not None else {}
    if not text or not policy.enabled:
        return text, stats
    text = redact_secrets(text, policy.secrets, stats)
    text = redact_personal(text, policy.patterns, stats)
    return text, stats


def redact_source(text: str, config: dict | None) -> str:
    """Segredos de leituras de código (``code:read``, ``file:read``, ``context:pack``)."""
    policy = get_policy(config)
    if not policy.enabled or not text:
        return text
    return redact_secrets(text, policy.secrets)


def format_stats(stats: dict) -> str:
    return ", ".join(f"{key}={stats[key]}" for key in sorted(stats))


def merge_stats(target: dict, other: dict) -> dict:
    for key, value in other.items():
        target[key] = target.get(key, 0) + value
    return target


# ---------------------------------------------------------------------------
# Colunas (db:query)
# ---------------------------------------------------------------------------
def column_matches(rules, table: str | None, column: str) -> bool:
    """``rules`` são globs ``tabela.coluna`` (sem ponto = qualquer tabela)."""
    target = f"{(table or '').lower()}.{(column or '').lower()}"
    for rule in rules:
        rule = str(rule).lower().strip()
        if not rule:
            continue
        if "." not in rule:
            rule = f"*.{rule}"
        if fnmatch.fnmatch(target, rule):
            return True
    return False


def mask_rows(rows: list[list[str]], masked: set[int]) -> tuple[list[list[str]], int]:
    """Substitui as colunas ``masked`` (índices) em cada linha."""
    count = 0
    out = []
    for row in rows:
        new_row = list(row)
        for index in masked:
            if index < len(new_row) and new_row[index] != "NULL":
                new_row[index] = MASK_COLUMN
                count += 1
        out.append(new_row)
    return out, count
