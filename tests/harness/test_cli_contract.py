"""Contrato dos comandos por pack e do CLI comum (D3.10)."""

import yaml

from commands.complements.harness_core import cli
from commands.harness_clean import HarnessCleanCommand
from commands.harness_exec import HarnessExecCommand
from commands.harness_patch import HarnessPatchCommand
from commands.harness_state import HarnessStateCommand
from commands.harness_validate import HarnessValidateCommand
from commands.harness_watch import HarnessWatchCommand


def test_commands_have_pack_and_name():
    expected = {
        HarnessExecCommand: ("harness-exec", "harness_exec"),
        HarnessPatchCommand: ("harness-patch", "harness_patch"),
        HarnessValidateCommand: ("harness-validate", "harness_validate"),
        HarnessStateCommand: ("harness-state", "harness_state"),
        HarnessWatchCommand: ("harness-watch", "harness_watch"),
        HarnessCleanCommand: ("harness-clean", "harness_clean"),
    }
    for cls, (name, pack) in expected.items():
        assert cls.name == name
        assert cls.pack == pack


def test_cli_tasks_counts_by_pack():
    ok, data = cli.execute("harness", ["tasks"])

    assert ok is True
    assert data["count"] == 17


def test_cli_tasks_exec_pack_counts():
    ok, data = cli.execute("harness_exec", ["tasks"])

    assert ok is True
    assert data["count"] == 7


def test_cli_rejects_unknown_subcommand():
    ok, data = cli.execute("harness_exec", ["nada"])

    assert ok is False
    assert "error" in data


def test_cli_shortcut_maps_to_task():
    ok, data = cli.execute("harness_state", ["list"])

    assert ok is True
    assert data["status"] == "success"


def test_cli_respects_plugins_enabled_false(tmp_path):
    (tmp_path / "repo").mkdir()
    config = {
        "workspace": str(tmp_path / "ws"),
        "legacy": {"repo_path": str(tmp_path / "repo")},
        "plugins": {"exec": {"enabled": False}},
    }
    path = tmp_path / "harness.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")

    ok, data = cli.execute("harness_exec", ["tasks", "--config", str(path)])

    assert ok is False
    assert data["error"] == "plugin desabilitado"
