"""Regressões da remoção das notas e do kb:export (R0.11)."""

from pathlib import Path

from commands.complements.harness.catalog import get_task, load_tasks
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import jit

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "commands" / "complements" / "harness" / "harness.example.yaml"


def test_removed_tasks_are_not_registered():
    load_tasks()

    for name in ("notes:draft", "notes:save", "notes:stale", "kb:export"):
        assert get_task(name) is None, name


def test_example_config_has_no_notes_or_kb():
    text = EXAMPLE.read_text(encoding="utf-8")

    assert "notes_path" not in text
    assert "kb:" not in text
    assert 'ask_context: "map,db"' in text
    assert "state:" in text


def test_search_scope_notes_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(jit, "rg_bin", lambda ctx: "rg")
    (tmp_path / "repo").mkdir()
    ctx = TaskContext(
        config={"legacy": {"repo_path": str(tmp_path / "repo")}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )

    result = jit.handle_search(ctx, {"pattern": "x", "scope": "notes"})

    assert result.success is False
    assert "removido" in result.summary
