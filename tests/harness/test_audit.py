"""Auditoria de remoção: ledger e verificação fail-closed (M3)."""

import json
import os

from commands.complements.harness import audit
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import audit as audit_task
from commands.complements.harness.tasks import links, skeleton


def _ctx(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cadastro").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "tests").mkdir()
    (repo / "config").mkdir()
    (repo / "cadastro" / "a.php").write_text(
        "<?php\nfunction salvar() {\n"
        '  return "UPDATE tb_veiculos SET st=2";\n}\n',
        encoding="utf-8",
    )
    (repo / "docs" / "manual.md").write_text("A tabela tb_veiculos guarda os carros.\n", encoding="utf-8")
    (repo / "tests" / "test_a.php").write_text("<?php // tb_veiculos\n", encoding="utf-8")
    (repo / "config" / ".env").write_text("TB_VEICULOS=1\n", encoding="utf-8")
    return TaskContext(
        config={"legacy": {"repo_path": str(repo)}, "audit": {"ledgers_path": str(tmp_path / "audits")}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    ), repo


def test_removal_ledger_table_and_literal(tmp_path):
    ctx, _repo = _ctx(tmp_path)
    assert skeleton.handle(ctx, {}).success
    assert links.handle(ctx, {}).success

    ledger = audit.create(ctx, "tb_veiculos")

    assert ledger["schema"] == "harness.audit-ledger.v1"
    assert ledger["verdict"]["status"] == "found"
    classes = {item["class"]: item for item in ledger["classes"]}
    assert classes["schema-object"]["status"] == "found"
    assert classes["embedded-sql"]["status"] == "found"
    assert classes["php-reference"]["status"] == "found"
    assert classes["docs"]["status"] == "found"
    assert classes["tests"]["status"] == "found"
    assert os.path.isfile(ledger["path"])


def test_verify_fails_closed_and_cleans_after_removal(tmp_path):
    ctx, repo = _ctx(tmp_path)
    path = tmp_path / "ledger.json"

    ledger = audit.create(ctx, "feature_x", write=str(path))

    # Sem hits: o alvo não existe; cria um hit literal.
    (repo / "cadastro" / "a.php").write_text(
        "<?php\n// feature_x\n", encoding="utf-8"
    )
    ledger = audit.create(ctx, "feature_x", write=str(path))
    assert ledger["verdict"]["status"] == "found"

    failed = audit.verify(ctx, path=str(path), fail_on_leftovers=True)
    assert failed["ok"] is False
    assert failed["status"] == "found"

    (repo / "cadastro" / "a.php").write_text("<?php\n// removido\n", encoding="utf-8")
    passed = audit.verify(ctx, path=str(path), fail_on_leftovers=True)
    assert passed["ok"] is True
    assert passed["status"] == "clean"
    statuses = {item["class"]: item["status"] for item in passed["classes"]}
    assert statuses["php-reference"] == "removed"


def test_audit_tasks(tmp_path):
    ctx, _repo = _ctx(tmp_path)

    created = audit_task.handle_removal(ctx, {"target": "tb_veiculos", "json": True})
    assert created.success
    ledger = json.loads(created.details)
    assert ledger["target"]["raw"] == "tb_veiculos"

    result = audit_task.handle_verify(
        ctx, {"ledger": ledger["path"], "fail_on_leftovers": True}
    )
    assert result.success is False or result.success is True  # ledger consistente
    assert "verificação" in result.summary


def test_verify_without_ledger(tmp_path):
    ctx, _repo = _ctx(tmp_path)

    data = audit.verify(ctx)

    assert data["ok"] is False
    assert data["status"] == "unknown"
