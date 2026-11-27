"""Fluxo completo (T25): ask → bloco simulado → exec → state save → state load."""

import yaml

from commands.complements.harness_core.catalog import load_tasks
from commands.complements.harness_core.engine import HarnessEngine
from commands.harness import HarnessCommand
from commands.harness_state import HarnessStateCommand

STATE_BLOCK = """```crivonansky-state
tarefa: ajuste-veiculo
decisoes: [manter mysql_*]
arquivos: [cadastro/veiculo.php]
pendencias: [validar placa]
proximo_passo: propor o patch de salvar_veiculo
```"""


def _setup(tmp_path):
    load_tasks()
    repo = tmp_path / "repo" / "cadastro"
    repo.mkdir(parents=True)
    (repo / "veiculo.php").write_bytes(
        "<?php\r\nfunction salvar_veiculo() {\r\n  // Ação\r\n}\r\n".encode("latin-1")
    )
    ws = tmp_path / "ws"
    config = {
        "harness_version": 1, "workspace": str(ws),
        "output": {"default_sinks": ["stdout"], "max_chars": {"clipboard": 20000}},
        "policy": {"allowed_roots": [str(tmp_path / "repo"), str(ws)]},
        "legacy": {"repo_path": str(tmp_path / "repo"), "encoding": "latin-1"},
    }
    path = tmp_path / "harness.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(path), ws


def test_full_flow(tmp_path, capsys, monkeypatch):
    config_path, ws = _setup(tmp_path)
    cmd = HarnessCommand()

    # 1. skeleton (gera o mapa) e ask com contexto de mapa
    ok, _ = cmd.execute(["run", "code:skeleton", "--config", config_path])
    assert ok
    ok, _ = cmd.execute(["ask", "como salva o veiculo?", "--context", "map", "--budget", "800",
                         "--config", config_path])
    prompt = capsys.readouterr().out
    assert ok and "## Mapa do código" in prompt and "## Uso do orçamento" in prompt

    # 2. bloco simulado do chat, executado como origem LLM
    engine = HarnessEngine(config_path=config_path, interactive=False, sinks=["stdout"])
    results, error = engine.handle_text(
        "```crivonansky\nharness: 1\ntask: code:read\nparams:\n  file: cadastro/veiculo.php\n```",
        origin="llm",
    )
    assert error is None and results[0]["status"] == "success"
    assert "Ação" in results[0]["text"]

    # 3. state save pelo atalho (confirmação y), depois state load (D3: comando próprio)
    state_cmd = HarnessStateCommand()
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    ok, _ = state_cmd.execute(["save", "--content", STATE_BLOCK, "--config", config_path])
    assert ok
    capsys.readouterr()
    ok, _ = state_cmd.execute(["load", "--last", "--config", config_path])
    out = capsys.readouterr().out
    assert ok
    assert "propor o patch de salvar_veiculo" in out and "validar placa" in out
    assert "# Mapa do código" in out
