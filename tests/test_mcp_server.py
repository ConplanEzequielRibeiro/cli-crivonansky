"""Testes do servidor MCP (`mcp_server.py`) — sem dependências externas."""

import sys

import mcp_server


def _call(method, params=None, message_id=1):
    message = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return mcp_server.handle(message)


def test_initialize_echoes_protocol_and_includes_instructions():
    response = _call("initialize", {"protocolVersion": "2024-11-05"})[0]

    result = response["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "crivonansky"
    assert "code:skeleton" in result["instructions"]


def test_tools_list_exposes_core_tools():
    response = _call("tools/list")[0]

    names = {tool["name"] for tool in response["result"]["tools"]}
    assert {"tasks", "run", "exec", "ask"} <= names


def test_notifications_have_no_response():
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) == []


def test_unknown_tool_returns_jsonrpc_error():
    response = _call("tools/call", {"name": "nao-existe", "arguments": {}})[0]

    assert response["error"]["code"] == -32602


def test_schema_sets_are_json_schemas():
    for tool in mcp_server.TOOLS:
        assert tool["inputSchema"]["type"] == "object"
        assert isinstance(tool["description"], str) and tool["description"]


def _fake_catalog(intent):
    return {
        "code:skeleton": {
            "intent": "read",
            "description": "esqueleto",
            "required": [],
            "optional": ["level"],
        },
        "notes:save": {
            "intent": "write",
            "description": "salva ficha",
            "required": ["content"],
            "optional": [],
        },
    }


def test_run_read_task_builds_params_without_yes(monkeypatch):
    monkeypatch.setattr(mcp_server, "_catalog", lambda: _fake_catalog("read"))
    captured = {}

    def fake_invoke(argv, stdin_text=None):
        captured["argv"] = argv
        return "ok", False

    monkeypatch.setattr(mcp_server, "_invoke", fake_invoke)

    text, is_error = mcp_server.tool_run(
        {"task": "code:skeleton", "params": {"level": "map", "split_map": True}}
    )

    assert (text, is_error) == ("ok", False)
    assert captured["argv"] == [
        "run",
        "code:skeleton",
        "--param",
        "level=map",
        "--param",
        "split_map=true",
    ]


def test_run_list_param_is_joined_with_commas(monkeypatch):
    monkeypatch.setattr(mcp_server, "_catalog", lambda: _fake_catalog("read"))
    captured = {}

    def fake_invoke(argv, stdin_text=None):
        captured["argv"] = argv
        return "ok", False

    monkeypatch.setattr(mcp_server, "_invoke", fake_invoke)

    mcp_server.tool_run(
        {"task": "code:skeleton", "params": {"exclude": ["relatorios", "*_old.php"]}}
    )

    assert captured["argv"] == [
        "run",
        "code:skeleton",
        "--param",
        "exclude=relatorios,*_old.php",
    ]


def test_run_write_task_is_blocked_by_default(monkeypatch):
    monkeypatch.setattr(mcp_server, "_catalog", lambda: _fake_catalog("write"))
    monkeypatch.setattr(mcp_server, "ALLOW_WRITE", False)

    text, is_error = mcp_server.tool_run({"task": "notes:save"})

    assert is_error is True
    assert "CRIVONANSKY_ALLOW_WRITE" in text


def test_run_write_task_passes_yes_when_enabled(monkeypatch):
    monkeypatch.setattr(mcp_server, "_catalog", lambda: _fake_catalog("write"))
    monkeypatch.setattr(mcp_server, "ALLOW_WRITE", True)
    captured = {}

    def fake_invoke(argv, stdin_text=None):
        captured["argv"] = argv
        return "ok", False

    monkeypatch.setattr(mcp_server, "_invoke", fake_invoke)

    text, is_error = mcp_server.tool_run({"task": "notes:save", "params": {"content": "x"}})

    assert is_error is False
    assert captured["argv"][-1] == "--yes"


def test_run_unknown_task_suggests_close_names(monkeypatch):
    monkeypatch.setattr(mcp_server, "_catalog", lambda: _fake_catalog("read"))

    text, is_error = mcp_server.tool_run({"task": "code:skelton"})

    assert is_error is True
    assert "code:skeleton" in text


def test_run_without_catalog_still_runs_and_never_auto_confirms(monkeypatch):
    monkeypatch.setattr(mcp_server, "_catalog", lambda: None)
    captured = {}

    def fake_invoke(argv, stdin_text=None):
        captured["argv"] = argv
        return "ok", False

    monkeypatch.setattr(mcp_server, "_invoke", fake_invoke)

    text, is_error = mcp_server.tool_run({"task": "code:search"})

    assert (text, is_error) == ("ok", False)
    assert "--yes" not in captured["argv"]


def test_exec_requires_a_block(monkeypatch):
    monkeypatch.setattr(mcp_server, "_catalog", lambda: _fake_catalog("read"))

    text, is_error = mcp_server.tool_exec({"text": "   "})

    assert is_error is True
    assert "crivonansky" in text


def test_exec_forwards_stdin(monkeypatch):
    captured = {}

    def fake_invoke(argv, stdin_text=None):
        captured["argv"] = argv
        captured["stdin"] = stdin_text
        return "ok", False

    monkeypatch.setattr(mcp_server, "_invoke", fake_invoke)

    block = "```crivonansky\nharness: 1\ntask: code:search\n```"
    text, is_error = mcp_server.tool_exec({"text": block})

    assert (text, is_error) == ("ok", False)
    assert captured["argv"] == ["exec", "--stdin"]
    assert captured["stdin"] == block


def test_ask_builds_context_and_budget(monkeypatch):
    captured = {}

    def fake_invoke(argv, stdin_text=None):
        captured["argv"] = argv
        return "prompt", False

    monkeypatch.setattr(mcp_server, "_invoke", fake_invoke)

    mcp_server.tool_ask({"question": "como salva?", "context": "map,db", "budget": "800"})

    assert captured["argv"] == ["ask", "como salva?", "--context", "map,db", "--budget", "800"]


def test_invoke_appends_no_clipboard_to_the_cli(monkeypatch):
    captured = {}

    class Process:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(mcp_server.subprocess, "run", fake_run)

    text, is_error = mcp_server._invoke(["run", "code:search"])

    assert (text, is_error) == ("ok", False)
    assert captured["command"][:4] == [mcp_server.PYTHON, mcp_server.CLI, "harness", "run"]
    assert captured["command"][-1] == "--no-clipboard"
    assert captured["kwargs"]["cwd"] == mcp_server.CWD


def test_selftest_does_not_require_an_mcp_client(capsys):
    assert mcp_server.selftest() == 0
    output = capsys.readouterr().out
    assert '"tools"' in output
    assert sys.executable  # sanity: módulo importado no Python de teste
