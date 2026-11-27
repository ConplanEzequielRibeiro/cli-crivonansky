"""Política por origem: blocos do LLM não executam shell/py/docker (T03)."""

from commands.complements.harness_core.contract import CommandBlock
from commands.complements.harness_core.policy import check_policy, llm_task_denied
from commands.complements.harness_core.task_types import TaskSpec


def _spec(intent="read"):
    return TaskSpec(name="t", intent=intent, description="", required=[], optional=[],
                    handler=lambda ctx, params: None)


def _block(task):
    return CommandBlock(raw="", id="c-1", task=task, intent=None, params={})


def test_llm_origin_denies_shell_py_docker_by_default():
    for task in ("shell:run", "py:run", "docker:exec"):
        decision, reason = check_policy(_block(task), _spec(), {}, True, False, False, origin="llm")
        assert decision == "deny"
        assert "linha de comando" in reason


def test_user_origin_is_not_denied():
    decision, _ = check_policy(_block("shell:run"), _spec(), {}, True, True, False, origin="user")

    assert decision == "allow"


def test_origin_defaults_from_yes_allowed():
    assert check_policy(_block("py:run"), _spec(), {}, True, False, False)[0] == "deny"
    assert check_policy(_block("py:run"), _spec(), {}, True, True, False)[0] == "allow"


def test_llm_allowed_tasks_wins_over_denied():
    policy = {"llm_allowed_tasks": ["code:read"], "llm_denied_tasks": []}

    assert llm_task_denied(policy, "code:read") is None
    assert "llm_allowed_tasks" in llm_task_denied(policy, "code:search")


def test_custom_denied_list_replaces_default():
    policy = {"llm_denied_tasks": ["patch:apply"]}

    assert llm_task_denied(policy, "patch:apply")
    assert llm_task_denied(policy, "shell:run") is None
