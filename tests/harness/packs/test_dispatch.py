"""Dispatch por dono: carrega o pack da tarefa sob demanda."""

import pytest

from commands.complements.harness_core import catalog
from commands.complements.harness_core.task_types import TaskContext


def _ctx(tmp_path):
    return TaskContext(
        config={"legacy": {"repo_path": str(tmp_path / "repo")}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def test_dispatch_resolves_owner_pack(tmp_path):
    result = catalog.dispatch("state:list", _ctx(tmp_path), {})

    assert result.success
    assert "nenhum estado" in result.summary


def test_dispatch_rejects_unknown_task(tmp_path):
    with pytest.raises(KeyError, match="inexistente"):
        catalog.dispatch("inexistente", _ctx(tmp_path), {})
