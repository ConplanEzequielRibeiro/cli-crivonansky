"""Roteamento do MCP por dono da tarefa (D5.2)."""

from mcp_server import _command_for


def test_command_for_mapping_and_core():
    assert _command_for("code:search") == "harness"
    assert _command_for("env:check") == "harness"
    assert _command_for("prompt") == "harness"


def test_command_for_capability_packs():
    assert _command_for("shell:run") == "harness-exec"
    assert _command_for("patch:apply") == "harness-patch"
    assert _command_for("verify") == "harness-validate"
    assert _command_for("state:save") == "harness-state"
    assert _command_for("watch:clip") == "harness-watch"
    assert _command_for("clean:runs") == "harness-clean"


def test_command_for_unknown_falls_back_to_mapping():
    assert _command_for("inexistente") == "harness"
