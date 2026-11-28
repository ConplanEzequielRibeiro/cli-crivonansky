"""O bloco ``crivonansky-result`` do core deve bater com o do harness."""

from commands.complements.harness_core import formatter
from core import result_block


def test_core_block_matches_harness_result_format():
    kwargs = {
        "block_id": "c-12345678",
        "task": "help",
        "status": "success",
        "exit_code": 0,
        "duration_ms": 7,
        "summary": "ajuda de 2 comando(s)",
        "details": "Comandos disponíveis (2):\n\nUso: /x",
        "artifacts": [],
        "max_chars": 12000,
        "hint": "",
    }

    assert result_block.format_result(**kwargs) == formatter.format_result(**kwargs)


def test_core_block_lists_artifacts_like_the_harness():
    kwargs = {
        "block_id": "c-12345678",
        "task": "help",
        "status": "success",
        "exit_code": 0,
        "duration_ms": 7,
        "summary": "ok",
        "details": "",
        "artifacts": ["a/b.md", "c/d.json"],
        "max_chars": 12000,
        "hint": "",
    }

    core_text, _ = result_block.format_result(**kwargs)
    harness_text, _ = formatter.format_result(**kwargs)

    assert core_text == harness_text
    assert "artifacts:\n  - a/b.md\n  - c/d.json" in core_text
