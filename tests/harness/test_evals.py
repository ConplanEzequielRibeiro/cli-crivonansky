"""Evals do brief: métricas determinísticas (M5)."""

import os

from commands.complements.harness import evals
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import links, skeleton


def _ctx(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cadastro").mkdir(parents=True)
    (repo / "cadastro" / "a.php").write_text(
        "<?php\nfunction salvar() {\n"
        '  return "UPDATE tb_veiculos SET st=2";\n}\n',
        encoding="utf-8",
    )
    (repo / "cadastro" / "b.php").write_text(
        "<?php\nfunction listar() {\n"
        '  return "SELECT * FROM tb_veiculos";\n}\n',
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


def test_evaluate_and_run(tmp_path):
    ctx = _ctx(tmp_path)
    gold = [
        {
            "id": "veiculos",
            "anchor": "table",
            "value": "tb_veiculos",
            "expected": ["cadastro/a.php", "cadastro/b.php"],
        }
    ]

    data = evals.evaluate(ctx, gold=gold, max_paths=5)

    assert data["schema"] == "harness.evals.v1"
    assert data["aggregate"]["tasks"] == 1
    assert data["aggregate"]["recall_at_5"] == 1.0
    assert data["aggregate"]["baseline_recall_at_5"] <= data["aggregate"]["recall_at_5"]
    assert data["cases"][0]["brief_tokens"] > 0
    assert data["aggregate"]["truncated"] == 0

    data, path = evals.run(ctx, gold=gold)
    assert os.path.isfile(path)
    assert "evals:" in evals.describe(data)


def test_evaluate_reports_missing_anchor(tmp_path):
    ctx = _ctx(tmp_path)
    gold = [
        {"id": "nada", "anchor": "table", "value": "tb_inexistente", "expected": []}
    ]

    data = evals.evaluate(ctx, gold=gold)

    assert data["cases"][0]["read_first"] == []
    assert data["aggregate"]["recall_at_5"] == 0.0
