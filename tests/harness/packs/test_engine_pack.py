"""Engine com escopo de pack: nega tarefa de outro dono e aplica o default do LLM."""

from commands.complements.harness_core.engine import HarnessEngine


def _config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    return {
        "workspace": str(tmp_path / "ws"),
        "legacy": {"repo_path": str(repo)},
        "output": {"default_sinks": ["stdout"]},
        "policy": {},
    }


def _block(task, params=""):
    if not params:
        return f"harness: 1\ntask: {task}\nparams: {{}}\n"
    body = "\n".join(f"  {line}" for line in params.splitlines())
    return f"harness: 1\ntask: {task}\nparams:\n{body}\n"


def test_foreign_task_is_denied_with_destination(tmp_path):
    engine = HarnessEngine(config=_config(tmp_path), interactive=False, dry_run=True, pack="harness")

    text, status = engine.handle_block(_block("shell:run", "command: echo x"))

    assert status == "denied"
    assert "/harness-exec" in text


def test_core_task_is_allowed_in_any_pack(tmp_path):
    engine = HarnessEngine(config=_config(tmp_path), interactive=False, dry_run=True, pack="harness")

    _text, status = engine.handle_block(_block("prompt"))

    assert status == "success"


def test_default_llm_denied_is_enforced_for_pack(tmp_path):
    engine = HarnessEngine(
        config=_config(tmp_path), interactive=False, dry_run=True, pack="harness_exec"
    )

    text, status = engine.handle_block(_block("shell:run", "command: echo x"))

    assert status == "denied"
    assert "bloco do LLM" in text


def test_user_can_run_pack_task(tmp_path):
    engine = HarnessEngine(
        config=_config(tmp_path),
        interactive=False,
        yes=True,
        dry_run=True,
        pack="harness_exec",
    )

    _text, status = engine.handle_block(
        _block("shell:run", "command: echo x"), yes_allowed=True
    )

    assert status == "success"
