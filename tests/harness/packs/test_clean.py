"""Testes das tarefas de limpeza (clean:artifacts / clean:runs)."""

import json
import os
import time

from commands.complements.harness_clean.tasks import clean
from commands.complements.harness_core.task_types import TaskContext


def _ctx(tmp_path):
    return TaskContext(
        config={"legacy": {"repo_path": str(tmp_path / "repo")}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def _make_artifacts(tmp_path):
    ws = tmp_path / "ws"
    files = {
        "knowledge/skeleton/project.json": "{}",
        "knowledge/db/schema-catalog.json": "{}",
        "knowledge/links/code-db-links.json": "[]",
        "knowledge/docs/manifest.json": "{}",
        "knowledge/code/src/app.php": "<?php\n",
        "knowledge/notes/ficha.md": "# ficha\n",
        "harness.yaml": "workspace: ws\n",
    }
    for relative, content in files.items():
        path = ws / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return ws


def test_artifacts_dry_run_lists_without_removing(tmp_path):
    ws = _make_artifacts(tmp_path)

    result = clean.handle_artifacts(_ctx(tmp_path), {"dry_run": "true"})

    assert result.success
    assert "seriam removidas" in result.summary
    assert (ws / "knowledge" / "skeleton").is_dir()
    assert (ws / "knowledge" / "notes" / "ficha.md").is_file()
    assert "knowledge/skeleton" in result.details


def test_artifacts_all_removes_generated_keeps_notes_and_config(tmp_path):
    ws = _make_artifacts(tmp_path)

    result = clean.handle_artifacts(_ctx(tmp_path), {})

    assert result.success
    for name in ("skeleton", "db", "links", "docs", "code"):
        assert not (ws / "knowledge" / name).exists()
    assert (ws / "knowledge" / "notes" / "ficha.md").is_file()
    assert (ws / "harness.yaml").is_file()


def test_artifacts_scope_subset(tmp_path):
    ws = _make_artifacts(tmp_path)

    result = clean.handle_artifacts(_ctx(tmp_path), {"scope": "skeleton"})

    assert result.success
    assert not (ws / "knowledge" / "skeleton").exists()
    assert (ws / "knowledge" / "db").is_dir()


def test_artifacts_unknown_scope(tmp_path):
    _make_artifacts(tmp_path)

    result = clean.handle_artifacts(_ctx(tmp_path), {"scope": "tudo"})

    assert result.success is False
    assert "scope desconhecido" in result.summary


def test_artifacts_nothing_to_clean(tmp_path):
    (tmp_path / "ws").mkdir()

    result = clean.handle_artifacts(_ctx(tmp_path), {})

    assert result.success
    assert result.summary == "nada a limpar"


def test_clean_intent_is_read_when_dry_run():
    assert clean._intent({"dry_run": "true"}) == "read"
    assert clean._intent({}) == "write"


def _make_runs(tmp_path, ids, ages_days):
    ws = tmp_path / "ws"
    runs = ws / "runs"
    runs.mkdir(parents=True)
    records = []
    for run_id, age in zip(ids, ages_days):
        folder = runs / run_id
        folder.mkdir()
        (folder / "result.md").write_text("ok\n", encoding="utf-8")
        timestamp = time.time() - age * 86_400
        os.utime(folder, (timestamp, timestamp))
        records.append({"id": run_id, "task": "code:read", "status": "success"})
    (runs / "runs.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\nlinha invalida\n",
        encoding="utf-8",
    )
    return runs


def test_clean_runs_removes_old_and_compacts_index(tmp_path):
    ids = ["c-00000001", "c-00000002", "c-00000003", "c-00000004", "c-00000005"]
    runs = _make_runs(tmp_path, ids, ages_days=[40, 40, 1, 1, 1])

    result = clean.handle_runs(_ctx(tmp_path), {"days": 30, "keep": 2})

    assert result.success
    assert [item for item in ids if (runs / item).is_dir()] == [
        "c-00000003",
        "c-00000004",
        "c-00000005",
    ]
    index = (runs / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(index) == 3
    assert {json.loads(line)["id"] for line in index} == set(ids[2:])


def test_clean_runs_dry_run_keeps_everything(tmp_path):
    ids = ["c-00000001", "c-00000002"]
    runs = _make_runs(tmp_path, ids, ages_days=[40, 40])

    result = clean.handle_runs(
        _ctx(tmp_path), {"days": 0, "keep": 0, "dry_run": "true"}
    )

    assert result.success
    assert all((runs / run_id).is_dir() for run_id in ids)
    assert "seriam removidas" in result.summary


def test_clean_runs_keep_recent(tmp_path):
    ids = ["c-00000001", "c-00000002", "c-00000003"]
    runs = _make_runs(tmp_path, ids, ages_days=[40, 30, 20])

    result = clean.handle_runs(_ctx(tmp_path), {"days": 0, "keep": 1})

    assert result.success
    assert (runs / "c-00000003").is_dir()
    assert not (runs / "c-00000001").exists()
    assert not (runs / "c-00000002").exists()


def test_clean_runs_ignores_non_run_entries(tmp_path):
    runs = _make_runs(tmp_path, ["c-00000001"], ages_days=[40])
    (runs / "rag-api.log").write_text("log\n", encoding="utf-8")
    other = runs / "notes-tmp"
    other.mkdir()

    result = clean.handle_runs(_ctx(tmp_path), {"days": 0, "keep": 0})

    assert result.success
    assert (runs / "rag-api.log").is_file()
    assert other.is_dir()
