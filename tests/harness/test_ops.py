"""Testes das operações de ciclo de vida do plugin (ops/config_template)."""

from pathlib import Path

from commands.complements.harness import config_template, ops
from commands.complements.harness.runner import ProcessResult
from commands.complements.harness.task_types import TaskResult


def test_config_template_renders_plugin_root(tmp_path):
    root = tmp_path / "harness"
    root.mkdir()
    (root / "harness.example.yaml").write_text(
        "workspace: \"{{PLUGIN_ROOT}}/workspace\"\n", encoding="utf-8"
    )

    rendered = config_template.render(root)

    assert "{{PLUGIN_ROOT}}" not in rendered
    assert root.as_posix() in rendered


def test_write_default_config_keeps_existing_unless_forced(tmp_path):
    root = tmp_path / "harness"
    root.mkdir()
    (root / "harness.example.yaml").write_text("a: 1\n", encoding="utf-8")

    target = config_template.write_default_config(root)
    assert target.read_text(encoding="utf-8") == "a: 1\n"

    target.write_text("manual: true\n", encoding="utf-8")
    config_template.write_default_config(root)
    assert target.read_text(encoding="utf-8") == "manual: true\n"

    config_template.write_default_config(root, force=True)
    assert target.read_text(encoding="utf-8") == "a: 1\n"


def test_resolve_config_uses_env(tmp_path, monkeypatch):
    config = tmp_path / "custom.yaml"
    config.write_text("workspace: ws\n", encoding="utf-8")
    monkeypatch.setenv("HARNESS_CONFIG", str(config))

    assert ops.resolve_config() == str(config)


def test_install_calls_plugin_installer(tmp_path, monkeypatch):
    plugin = tmp_path / "harness"
    plugin.mkdir()
    (plugin / "install.ps1").write_text("# fake\n", encoding="utf-8")

    calls = {}

    def fake_run(cmd, cwd=None, timeout=60, shell=False, env=None, stream=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        calls["stream"] = stream
        return ProcessResult(0, "ok", "")

    written = {}

    def fake_write(root, force=False):
        written["force"] = force
        return Path(root) / "workspace" / "harness.yaml"

    monkeypatch.setattr(ops, "PLUGIN_ROOT", plugin)
    monkeypatch.setattr(ops, "run_process", fake_run)
    monkeypatch.setattr(ops, "write_default_config", fake_write)

    result = ops.install(force=True)

    assert result.success is True
    assert calls["cmd"][:2] == ["powershell", "-NoProfile"]
    assert "-ForceConfig" in calls["cmd"]
    assert written["force"] is True


def test_install_passes_python_override_and_stream(tmp_path, monkeypatch):
    plugin = tmp_path / "harness"
    plugin.mkdir()
    (plugin / "install.ps1").write_text("# fake\n", encoding="utf-8")

    calls = {}

    def fake_run(cmd, cwd=None, timeout=60, shell=False, env=None, stream=None):
        calls["cmd"] = cmd
        calls["stream"] = stream
        return ProcessResult(0, "ok", "")

    monkeypatch.setattr(ops, "PLUGIN_ROOT", plugin)
    monkeypatch.setattr(ops, "run_process", fake_run)
    monkeypatch.setattr(ops, "write_default_config", lambda root, force=False: Path(root) / "workspace" / "harness.yaml")

    result = ops.install(python_exe=r"C:\Python314\python.exe")

    assert result.success is True
    assert "-PythonExe" in calls["cmd"]
    assert r"C:\Python314\python.exe" in calls["cmd"]
    assert callable(calls["stream"])


def test_install_reports_missing_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "PLUGIN_ROOT", tmp_path)

    result = ops.install()

    assert result.success is False
    assert "instalador não encontrado" in result.summary


def test_install_forwards_with_rag(tmp_path, monkeypatch):
    plugin = tmp_path / "harness"
    plugin.mkdir()
    (plugin / "install.ps1").write_text("# fake\n", encoding="utf-8")

    calls = {}

    def fake_run(cmd, cwd=None, timeout=60, shell=False, env=None, stream=None):
        calls["cmd"] = cmd
        return ProcessResult(0, "ok", "")

    monkeypatch.setattr(ops, "PLUGIN_ROOT", plugin)
    monkeypatch.setattr(ops, "run_process", fake_run)
    monkeypatch.setattr(
        ops,
        "write_default_config",
        lambda root, force=False: Path(root) / "workspace" / "harness.yaml",
    )

    result = ops.install(with_rag=True)

    assert result.success is True
    assert "-WithRag" in calls["cmd"]


def test_prepare_indexes_skeleton_before_links(monkeypatch):
    tasks = []

    monkeypatch.setattr(ops, "start", lambda **kwargs: TaskResult(True, "start ok"))
    monkeypatch.setattr(ops, "ensure_config", lambda *args, **kwargs: "cfg")
    monkeypatch.setattr(ops, "_set_db_env", lambda *args, **kwargs: None)

    def fake_task(config, task, params=None):
        tasks.append(task)
        return TaskResult(True, f"{task} ok")

    monkeypatch.setattr(ops, "_run_task", fake_task)

    result = ops.prepare()

    assert result.success is True
    assert tasks == ["db:snapshot", "code:skeleton", "db:links", "docs:import"]


def test_prepare_runs_rag_sync_only_when_asked(monkeypatch):
    tasks = []

    monkeypatch.setattr(ops, "start", lambda **kwargs: TaskResult(True, "start ok"))
    monkeypatch.setattr(ops, "ensure_config", lambda *args, **kwargs: "cfg")
    monkeypatch.setattr(ops, "_set_db_env", lambda *args, **kwargs: None)

    def fake_task(config, task, params=None):
        tasks.append(task)
        return TaskResult(True, f"{task} ok")

    monkeypatch.setattr(ops, "_run_task", fake_task)

    ops.prepare(sync=True)

    assert tasks == ["db:snapshot", "code:skeleton", "db:links", "docs:import", "rag:sync"]


def test_config_info_includes_profile_and_skeleton(tmp_path, monkeypatch):
    import json

    plugin = tmp_path / "harness"
    workspace = plugin / "workspace"
    workspace.mkdir(parents=True)
    config = workspace / "harness.yaml"
    config.write_text(
        f"workspace: {workspace.as_posix()}\n"
        "legacy:\n"
        "  stack: java-oracle\n"
        f"  repo_path: {(tmp_path / 'repo').as_posix()}\n"
        "tools:\n"
        "  python: python\n",
        encoding="utf-8",
    )
    skeleton = workspace / "knowledge" / "skeleton"
    skeleton.mkdir(parents=True)
    (skeleton / "project.json").write_text(
        json.dumps({"files": 3, "symbols": 7, "stack": "java-oracle"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(ops, "PLUGIN_ROOT", plugin)

    info = ops.config_info()

    assert info["stack"] == "java-oracle"
    assert info["db_dialect"] == "oracle"
    assert info["encoding"] == "utf-8"
    assert ".java" in info["extensions"]
    assert info["skeleton"] == "3 arquivo(s), 7 símbolo(s)"
    assert info["skeleton_stack"] == "java-oracle"


def _stub_start(monkeypatch, rag_result=None):
    calls = {"docker": 0, "powershell": 0, "tasks": []}

    monkeypatch.setattr(ops, "ensure_config", lambda *args, **kwargs: "cfg")
    monkeypatch.setattr(ops, "_set_db_env", lambda *args, **kwargs: None)

    def fake_docker():
        calls["docker"] += 1
        return True

    def fake_powershell(*args, **kwargs):
        calls["powershell"] += 1
        return ProcessResult(0, "fixture ok", "")

    def fake_task(config, task, params=None):
        calls["tasks"].append((task, params))
        return rag_result or TaskResult(True, "rag ok")

    monkeypatch.setattr(ops, "_docker_available", fake_docker)
    monkeypatch.setattr(ops, "_powershell", fake_powershell)
    monkeypatch.setattr(ops, "_run_task", fake_task)
    return calls


def test_start_no_docker_skips_fixture(monkeypatch):
    calls = _stub_start(monkeypatch)

    result = ops.start(no_docker=True, with_rag=True)

    assert result.success is True
    assert calls["docker"] == 0
    assert calls["powershell"] == 0
    assert calls["tasks"] == [("rag:serve", {"action": "start"})]
    assert "fixture não iniciada" in result.summary


def test_start_no_docker_without_rag_is_noop(monkeypatch):
    calls = _stub_start(monkeypatch)

    result = ops.start(no_docker=True)

    assert result.success is True
    assert calls["docker"] == 0
    assert calls["powershell"] == 0
    assert calls["tasks"] == []
    assert "nada a iniciar" in result.summary


def test_start_no_docker_reports_rag_failure(monkeypatch):
    _stub_start(monkeypatch, rag_result=TaskResult(False, "rag falhou", exit_code=1))

    result = ops.start(no_docker=True, with_rag=True)

    assert result.success is False
    assert result.summary == "API do RAG não iniciou"


def test_start_without_no_docker_starts_fixture(monkeypatch):
    calls = _stub_start(monkeypatch)

    result = ops.start(with_rag=True)

    assert result.success is True
    assert calls["docker"] == 1
    assert calls["powershell"] == 1
    assert calls["tasks"] == [("rag:serve", {"action": "start"})]
    assert result.summary == "ambiente do harness no ar"


def test_start_does_not_touch_rag_by_default(monkeypatch):
    calls = _stub_start(monkeypatch)

    result = ops.start()

    assert result.success is True
    assert calls["docker"] == 1
    assert calls["tasks"] == []
    assert result.summary == "fixture no ar (RAG não iniciado)"
