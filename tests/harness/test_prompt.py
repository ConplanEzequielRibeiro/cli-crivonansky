"""Prompt do LLM: catálogo vivo e o mesmo pipeline de saída das demais tarefas."""

import sys
import types

from commands.complements.harness_core.catalog import load_tasks
from commands.complements.harness_core.engine import HarnessEngine
from commands.complements.harness_core.task_types import TaskContext
from commands.complements.harness.tasks import prompt


def _config(tmp_path, sinks=("stdout",), plugins=None):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    config = {
        "workspace": str(tmp_path / "ws"),
        "legacy": {"repo_path": str(repo)},
        "output": {"default_sinks": list(sinks)},
        "policy": {},
    }
    if plugins:
        config["plugins"] = plugins
    return config


def _ctx(config=None):
    return TaskContext(config=config or {"policy": {}}, workspace=".", run_dir=".")


def _fake_clipboard(monkeypatch):
    copied: list[str] = []
    module = types.ModuleType("pyperclip")
    module.copy = copied.append
    module.paste = lambda: ""
    monkeypatch.setitem(sys.modules, "pyperclip", module)
    return copied


def test_prompt_lists_every_current_task():
    load_tasks()

    text = prompt.handle(_ctx(), {}).details

    # Tarefas que entraram depois do prompt antigo (lista fixa) precisam aparecer.
    for name in (
        "code:brief",
        "knowledge:verify",
        "audit:removal",
        "audit:verify",
        "graph:stats",
        "graph:export",
        "db:snapshot",
        "clean:artifacts",
        "state:save",
        "patch:apply",
        "code:skeleton",
    ):
        assert f"`{name}`" in text
    assert "## Catálogo" in text


def test_prompt_follows_the_registry_instead_of_a_hardcoded_list(monkeypatch):
    original = prompt.packs.pack_tasks
    monkeypatch.setattr(
        prompt.packs,
        "pack_tasks",
        lambda pack: ["code:nova", "code:skeleton"] if pack == "harness" else original(pack),
    )

    text = prompt.handle(_ctx(), {}).details

    assert "`code:nova`" in text


def test_prompt_exposes_params_and_intent():
    load_tasks()

    text = prompt.handle(_ctx(), {}).details

    assert "`code:read` (read) (file, start?, end?, max_lines?)" in text
    assert "`db:query` (read) (sql, limit?)" in text


def test_prompt_skips_disabled_packs():
    config = {"policy": {}, "plugins": {"exec": {"enabled": False}}}

    text = prompt.handle(_ctx(config), {}).details

    assert "/harness-exec" not in text
    assert "/harness-patch" in text


def test_prompt_lists_tasks_denied_to_llm_blocks():
    text = prompt.handle(_ctx(), {}).details

    assert "Blocos do LLM NÃO executam:" in text
    for name in ("shell:run", "patch:apply", "git:run", "watch:clip"):
        assert f"`{name}`" in text


def test_prompt_output_is_a_result_block_copied_to_the_clipboard(tmp_path, monkeypatch):
    copied = _fake_clipboard(monkeypatch)
    engine = HarnessEngine(
        config=_config(tmp_path, sinks=("stdout", "clipboard")),
        interactive=False,
        pack="harness",
    )

    text, status = engine.handle_block("harness: 1\ntask: prompt\nparams: {}\n")

    assert status == "success"
    assert text.startswith("```crivonansky-result")
    assert "task: prompt" in text
    assert copied == [text]


def test_prompt_does_not_touch_the_clipboard_on_its_own(tmp_path, monkeypatch):
    copied = _fake_clipboard(monkeypatch)
    engine = HarnessEngine(
        config=_config(tmp_path, sinks=("stdout",)),
        interactive=False,
        pack="harness",
    )

    text, status = engine.handle_block("harness: 1\ntask: prompt\nparams: {}\n")

    assert status == "success"
    assert text.startswith("```crivonansky-result")
    assert copied == []


def _write_config(tmp_path, sinks):
    import yaml

    path = tmp_path / "harness.yaml"
    path.write_text(
        yaml.safe_dump(_config(tmp_path, sinks=sinks), allow_unicode=True),
        encoding="utf-8",
    )
    return str(path)


def test_cli_prompt_copies_the_result_block(tmp_path, monkeypatch):
    from commands.complements.harness_core import cli

    path = _write_config(tmp_path, ("stdout", "clipboard"))
    copied = _fake_clipboard(monkeypatch)

    ok, _data = cli.execute("harness", ["prompt", "--config", path])

    assert ok is True
    assert len(copied) == 1
    assert copied[0].startswith("```crivonansky-result")


def test_cli_prompt_no_clipboard_keeps_the_clipboard_intact(tmp_path, monkeypatch):
    from commands.complements.harness_core import cli

    path = _write_config(tmp_path, ("stdout", "clipboard"))
    copied = _fake_clipboard(monkeypatch)

    ok, _data = cli.execute("harness", ["prompt", "--no-clipboard", "--config", path])

    assert ok is True
    assert copied == []
