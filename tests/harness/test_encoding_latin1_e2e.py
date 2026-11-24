"""Legado ISO-8859-1/CRLF de ponta a ponta pelo engine (T04) + redação e política."""

import subprocess

import pytest
import yaml

from commands.complements.harness.catalog import load_tasks
from commands.complements.harness.engine import HarnessEngine
from commands.complements.harness.tasks import patch as patch_task
from commands.complements.harness.task_types import TaskContext

SOURCE = (
    "<?php\r\n"
    "// Cadastro de veículos - Ação\r\n"
    "$cpf = '529.982.247-25';\r\n"
    "$senha = 'segredo123';\r\n"
    "echo 'ok';\r\n"
)


@pytest.fixture
def setup(tmp_path):
    load_tasks()
    repo = tmp_path / "repo"
    (repo / "cadastro").mkdir(parents=True)
    (repo / "cadastro" / "veiculo.php").write_bytes(SOURCE.encode("latin-1"))
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "."], ["commit", "-q", "-m", "b"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    workspace = tmp_path / "ws"
    config = {
        "harness_version": 1,
        "workspace": str(workspace),
        "output": {"default_sinks": ["stdout"], "max_chars": {"clipboard": 20000}},
        "policy": {"deny_patterns": [], "auto_approve": ["read"], "confirm": ["write"],
                   "allowed_roots": [str(repo), str(workspace)]},
        "legacy": {"repo_path": str(repo), "encoding": "latin-1"},
    }
    path = tmp_path / "harness.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    engine = HarnessEngine(config_path=str(path), interactive=False, sinks=["stdout"])
    return engine, repo, workspace, config


def test_read_decodes_latin1_and_redacts_secrets_and_cpf(setup):
    engine, *_ = setup

    text, status = engine.handle_block(
        "harness: 1\ntask: file:read\nparams:\n  path: cadastro/veiculo.php\n"
    )

    assert status == "success"
    assert "Ação" in text and "�" not in text
    assert "529.982.247-25" not in text
    assert "segredo123" not in text
    assert "[redact:" in text


def test_llm_block_for_shell_is_denied_by_engine(setup):
    engine, *_ = setup

    text, status = engine.handle_block(
        "harness: 1\ntask: shell:run\nparams:\n  command: echo oi\n"
    )

    assert status == "denied"
    assert "linha de comando" in text


def test_patch_roundtrip_keeps_latin1_crlf_and_reads_back(setup):
    engine, repo, workspace, config = setup
    ctx = TaskContext(config=config, workspace=str(workspace), run_dir=str(workspace / "run"))
    diff = (
        "--- a/cadastro/veiculo.php\n+++ b/cadastro/veiculo.php\n"
        "@@ -4,2 +4,2 @@\n $senha = 'segredo123';\n-echo 'ok';\n+echo 'concluído';\n"
    )

    result = patch_task.handle(ctx, {"diff": diff, "branch": "ajuste"})

    assert result.success, result.details
    raw = (repo / "cadastro" / "veiculo.php").read_bytes()
    assert raw.endswith("echo 'concluído';\r\n".encode("latin-1"))
    assert b"\n" not in raw.replace(b"\r\n", b"")

    text, status = engine.handle_block(
        "harness: 1\ntask: file:read\nparams:\n  path: cadastro/veiculo.php\n"
    )
    assert status == "success" and "concluído" in text
