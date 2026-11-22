"""Testes do registro de perfis de stack."""

import pytest

from commands.complements.harness import filters
from commands.complements.harness.profiles import (
    STACK_PROFILES,
    normalize_extension,
    resolve_profile,
)
from commands.complements.harness.tasks import links


def test_default_profile_matches_php_mysql_behavior():
    profile = resolve_profile({})

    assert profile.name == "php-mysql"
    assert profile.code_extensions == frozenset(filters.CODE_EXTENSIONS)
    assert profile.sql_extensions == frozenset(links.EXTENSIONS)
    assert profile.db_dialect == "mysql"
    assert profile.encoding == "utf-8"
    assert profile.languages[".php"] == "php"


def test_builtin_profiles_are_registered():
    assert set(STACK_PROFILES) == {
        "php-mysql",
        "java-oracle",
        "dotnet-sqlserver",
        "ruby-postgres",
        "node-postgres",
        "custom",
    }


def test_java_profile():
    profile = resolve_profile({"legacy": {"stack": "java-oracle"}})

    assert ".java" in profile.code_extensions
    assert profile.languages[".java"] == "java"
    assert "java" in profile.definition_kinds
    assert profile.db_dialect == "oracle"


def test_overrides_extensions_languages_dialect_and_encoding():
    profile = resolve_profile(
        {
            "legacy": {
                "stack": "custom",
                "extensions": ["jsp", "JAVA"],
                "languages": {".jsp": "java"},
                "db_dialect": "oracle",
                "encoding": "cp1252",
            }
        }
    )

    assert profile.code_extensions == frozenset({".jsp", ".java"})
    assert profile.sql_extensions == frozenset({".jsp", ".java"})
    assert profile.languages[".jsp"] == "java"
    assert profile.db_dialect == "oracle"
    assert profile.encoding == "cp1252"


def test_sql_extensions_override_is_independent():
    profile = resolve_profile(
        {
            "legacy": {
                "stack": "php-mysql",
                "extensions": [".php"],
                "sql_extensions": [".php", ".sql"],
            }
        }
    )

    assert profile.code_extensions == frozenset({".php"})
    assert profile.sql_extensions == frozenset({".php", ".sql"})


def test_unknown_stack_raises():
    with pytest.raises(ValueError, match="legacy.stack"):
        resolve_profile({"legacy": {"stack": "cobol"}})


def test_normalize_extension():
    assert normalize_extension("JAVA") == ".java"
    assert normalize_extension(".rb") == ".rb"
    assert normalize_extension("") == ""
