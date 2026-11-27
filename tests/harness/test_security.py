"""Revisão de segurança: redaction em brief/audit e trilha de runs (X.1/X.3)."""

import json

from commands.complements.harness import audit
from commands.complements.harness_core.task_types import TaskContext
from commands.complements.harness.tasks import brief, links, skeleton


def _ctx(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cadastro").mkdir(parents=True)
    (repo / "cadastro" / "a.php").write_text(
        "<?php\nfunction salvar() {\n"
        "  return \"INSERT INTO tb_clientes (cpf) VALUES ('529.982.247-25')\";\n}\n",
        encoding="utf-8",
    )
    ctx = TaskContext(
        config={"legacy": {"repo_path": str(repo)}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )
    assert skeleton.handle(ctx, {}).success
    assert links.handle(ctx, {}).success
    return ctx


def test_brief_redacts_cpf(tmp_path):
    ctx = _ctx(tmp_path)

    result = brief.handle(ctx, {"table": "tb_clientes"})

    assert result.success
    assert "529.982.247-25" not in result.details


def test_audit_ledger_redacts_cpf(tmp_path):
    ctx = _ctx(tmp_path)

    ledger = audit.create(ctx, "tb_clientes", write=str(tmp_path / "ledger.json"))

    text = open(ledger["path"], encoding="utf-8").read()
    assert "529.982.247-25" not in text


def test_run_index_includes_pack(tmp_path):
    from commands.complements.harness_core.engine import HarnessEngine

    repo = tmp_path / "repo"
    repo.mkdir()
    config = {
        "workspace": str(tmp_path / "ws"),
        "legacy": {"repo_path": str(repo)},
        "output": {"default_sinks": ["stdout"]},
        "policy": {},
    }
    engine = HarnessEngine(config=config, interactive=False, dry_run=True)
    engine.handle_block("harness: 1\ntask: prompt\nparams: {}\n")

    record = engine.runs.last(1)[0]
    assert record["pack"] == "all"
    assert "result_chars" in record
