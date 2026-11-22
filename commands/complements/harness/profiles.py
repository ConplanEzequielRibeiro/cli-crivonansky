"""Perfis de stack: recorte de arquivos, linguagens e dialeto do banco.

O perfil é resolvido do ``harness.yaml`` (``legacy.stack`` + overrides) e mantém
o harness reutilizável em outras stacks sem espalhar ``if`` pelo código. O
perfil ``php-mysql`` reproduz o comportamento histórico (PHP/JS/TS/Python +
MySQL) e é o padrão.
"""

from dataclasses import dataclass, replace

from .filters import CODE_EXTENSIONS

DEFAULT_STACK = "php-mysql"

# Extensões que o `db:links` varre atrás de SQL embutido (histórico).
_PHP_SQL_EXTENSIONS = {".php", ".js", ".ts", ".jsx", ".tsx"}

# ---------------------------------------------------------------------------
# Linguagens (ast-grep) por extensão
# ---------------------------------------------------------------------------
EXTENSION_LANGUAGES = {
    ".php": "php",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".py": "python",
    ".java": "java",
    ".jsp": "java",
    ".cs": "csharp",
    ".rb": "ruby",
    ".erb": "ruby",
    ".go": "go",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".ex": "elixir",
    ".exs": "elixir",
}

# ---------------------------------------------------------------------------
# Kinds de definição por linguagem (ast-grep) -> rótulo exibido
# ---------------------------------------------------------------------------
DEFINITION_KINDS = {
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
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "record",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
    },
    "csharp": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "struct_declaration": "struct",
        "record_declaration": "record",
        "enum_declaration": "enum",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        "property_declaration": "property",
    },
    "ruby": {
        "class": "class",
        "module": "module",
        "method": "method",
        "singleton_method": "method",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_spec": "type",
    },
    "kotlin": {
        "class_declaration": "class",
        "object_declaration": "object",
        "function_declaration": "function",
        "property_declaration": "property",
    },
    "scala": {
        "class_definition": "class",
        "object_definition": "object",
        "trait_definition": "trait",
        "function_definition": "function",
    },
    "c": {
        "function_definition": "function",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
        "type_definition": "type",
    },
    "cpp": {
        "function_definition": "function",
        "class_specifier": "class",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
        "namespace_definition": "namespace",
    },
    # Elixir não expõe `def` como kind estável: fica no fallback por regex.
    "elixir": {},
}

# ---------------------------------------------------------------------------
# Imports/includes por linguagem
# ---------------------------------------------------------------------------
IMPORT_PATTERNS = {
    "php": r"^\s*(?:include|include_once|require|require_once)\b[^\n]*$",
    "javascript": (
        r"^\s*(?:import|export)\b[^\n]*from\s*['\"][^'\"]+['\"]"
        r"|^\s*(?:const|let|var)\s+\w+\s*=\s*require\([^\n]*\)"
    ),
    "typescript": (
        r"^\s*(?:import|export)\b[^\n]*from\s*['\"][^'\"]+['\"]"
        r"|^\s*(?:const|let|var)\s+\w+\s*=\s*require\([^\n]*\)"
    ),
    "python": r"^\s*(?:from\s+\S+\s+import\s+|import\s+)[^\n]*$",
    "java": r"^\s*import\s+(?:static\s+)?[\w.*]+\s*;",
    "csharp": r"^\s*using\s+[\w.]+\s*;",
    "ruby": r"^\s*require(?:_relative)?\s*['\"][^'\"]+['\"]",
    "go": r"^\s*import\s+(?:\(|\")[^\n]*",
    "kotlin": r"^\s*import\s+[\w.*]+\s*$",
    "scala": r"^\s*import\s+[\w.{}, _]+\s*$",
    "c": r"^\s*#\s*include\s*[<\"][^>\"]+[>\"]",
    "cpp": r"^\s*#\s*include\s*[<\"][^>\"]+[>\"]",
    "elixir": r"^\s*(?:alias|import|require|use)\s+[\w.]+",
}
IMPORT_PATTERNS["tsx"] = IMPORT_PATTERNS["typescript"]


def _kinds(*languages: str) -> dict[str, dict[str, str]]:
    return {language: DEFINITION_KINDS[language] for language in languages}


def _imports(*languages: str) -> dict[str, str]:
    return {language: IMPORT_PATTERNS[language] for language in languages}


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StackProfile:
    """Recorte de código/SQL de uma stack."""

    name: str
    label: str
    code_extensions: frozenset[str]
    sql_extensions: frozenset[str]
    languages: dict[str, str]
    definition_kinds: dict[str, dict[str, str]]
    import_patterns: dict[str, str]
    db_dialect: str
    encoding: str = "utf-8"


PHP_MYSQL = StackProfile(
    name="php-mysql",
    label="PHP/MySQL + JavaScript",
    code_extensions=frozenset(CODE_EXTENSIONS),
    sql_extensions=frozenset(_PHP_SQL_EXTENSIONS),
    languages={ext: EXTENSION_LANGUAGES[ext] for ext in CODE_EXTENSIONS},
    definition_kinds=_kinds("php", "javascript", "typescript", "tsx", "python"),
    import_patterns=_imports("php", "javascript", "typescript", "tsx", "python"),
    db_dialect="mysql",
)

JAVA_ORACLE = StackProfile(
    name="java-oracle",
    label="Java/Oracle",
    code_extensions=frozenset({".java", ".jsp"}),
    sql_extensions=frozenset({".java", ".jsp"}),
    languages={".java": "java", ".jsp": "java"},
    definition_kinds=_kinds("java"),
    import_patterns=_imports("java"),
    db_dialect="oracle",
)

DOTNET_SQLSERVER = StackProfile(
    name="dotnet-sqlserver",
    label=".NET/SQL Server",
    code_extensions=frozenset({".cs"}),
    sql_extensions=frozenset({".cs"}),
    languages={".cs": "csharp"},
    definition_kinds=_kinds("csharp"),
    import_patterns=_imports("csharp"),
    db_dialect="tsql",
)

RUBY_POSTGRES = StackProfile(
    name="ruby-postgres",
    label="Ruby/PostgreSQL",
    code_extensions=frozenset({".rb", ".erb"}),
    sql_extensions=frozenset({".rb", ".erb"}),
    languages={".rb": "ruby", ".erb": "ruby"},
    definition_kinds=_kinds("ruby"),
    import_patterns=_imports("ruby"),
    db_dialect="postgres",
)

NODE_POSTGRES = StackProfile(
    name="node-postgres",
    label="Node/PostgreSQL",
    code_extensions=frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}),
    sql_extensions=frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}),
    languages={
        ext: EXTENSION_LANGUAGES[ext]
        for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
    },
    definition_kinds=_kinds("javascript", "typescript", "tsx"),
    import_patterns=_imports("javascript", "typescript", "tsx"),
    db_dialect="postgres",
)

CUSTOM = StackProfile(
    name="custom",
    label="custom",
    code_extensions=frozenset(),
    sql_extensions=frozenset(),
    languages={},
    definition_kinds=_kinds(*DEFINITION_KINDS),
    import_patterns=_imports(*IMPORT_PATTERNS),
    db_dialect="mysql",
)

STACK_PROFILES = {
    profile.name: profile
    for profile in (PHP_MYSQL, JAVA_ORACLE, DOTNET_SQLSERVER, RUBY_POSTGRES, NODE_POSTGRES, CUSTOM)
}


def normalize_extension(value: str) -> str:
    """``java``/``.JAVA`` -> ``.java``."""
    value = str(value).strip().lower()
    if not value:
        return value
    return value if value.startswith(".") else f".{value}"


def resolve_profile(config: dict | None = None) -> StackProfile:
    """Resolve o perfil efetivo a partir de ``legacy.*`` no harness.yaml.

    Precedência: perfil (``legacy.stack``) -> overrides
    (``extensions``/``sql_extensions``/``languages``/``db_dialect``/``encoding``).
    """
    legacy = (config or {}).get("legacy") or {}
    name = str(legacy.get("stack") or DEFAULT_STACK).strip().lower().replace("_", "-")

    base = STACK_PROFILES.get(name)
    if base is None:
        available = ", ".join(sorted(STACK_PROFILES))
        raise ValueError(f"legacy.stack desconhecida: {name!r} (use: {available})")

    overrides = legacy.get("extensions")
    if overrides:
        code_extensions = {normalize_extension(item) for item in overrides if item}
    else:
        code_extensions = set(base.code_extensions)

    sql_overrides = legacy.get("sql_extensions")
    if sql_overrides:
        sql_extensions = {normalize_extension(item) for item in sql_overrides if item}
    elif overrides:
        sql_extensions = set(code_extensions)
    else:
        sql_extensions = set(base.sql_extensions)

    languages = dict(base.languages)
    for extension, language in (legacy.get("languages") or {}).items():
        normalized = normalize_extension(extension)
        if not normalized:
            continue
        languages[normalized] = str(language).strip()
        code_extensions.add(normalized)

    return replace(
        base,
        code_extensions=frozenset(code_extensions),
        sql_extensions=frozenset(sql_extensions),
        languages=languages,
        db_dialect=str(legacy.get("db_dialect") or base.db_dialect),
        encoding=str(legacy.get("encoding") or base.encoding),
    )
