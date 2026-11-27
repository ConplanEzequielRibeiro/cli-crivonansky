"""Hooks: default sem notas e migração de config antiga (R0.7)."""

from commands.complements.harness import hooks


def _config(tmp_path, tasks=None):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    config = {
        "workspace": str(tmp_path / "ws"),
        "legacy": {"repo_path": str(repo)},
    }
    if tasks is not None:
        config["hooks"] = {"tasks": tasks}
    return config


def test_default_hook_tasks_only_skeleton(tmp_path):
    tasks, _log, _repo = hooks._settings(_config(tmp_path))

    assert tasks == ["code:skeleton"]


def test_old_config_drops_notes_stale(tmp_path):
    tasks, _log, _repo = hooks._settings(_config(tmp_path, ["code:skeleton", "notes:stale"]))

    assert tasks == ["code:skeleton"]


def test_only_notes_falls_back_to_skeleton(tmp_path):
    tasks, _log, _repo = hooks._settings(_config(tmp_path, ["notes:stale"]))

    assert tasks == ["code:skeleton"]
