"""Roteamento do MCP por dono da tarefa (D5.2/M6)."""

from mcp_server import HANDLERS, TOOLS, tool_brief, _command_for


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


def test_mapping_tools_are_registered():
    names = {item["name"] for item in TOOLS}

    assert {"brief", "verify", "impact", "audit_removal", "audit_verify"} <= names
    assert {"brief", "verify", "impact", "audit_removal", "audit_verify"} <= set(HANDLERS)


def test_brief_requires_anchor_argument():
    text, error = tool_brief({})

    assert error is True
    assert "path" in text

