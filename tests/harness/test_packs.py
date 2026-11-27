"""Inventário congelado das tarefas e mapa de donos (B0.2).

Este teste é o contrato do desmembramento: nenhuma tarefa pode sumir, mudar de
assinatura ou de dono sem uma atualização explícita. A R0.2 removeu as três tarefas
`notes:*` e a R0.3 removeu `kb:export`, deixando 33 tarefas.
"""

import hashlib
import json
from collections import Counter

import pytest

from commands.complements.harness_core import packs
from commands.complements.harness_core.catalog import all_tasks, load_tasks

# Snapshot limpo no import do módulo: os testes de engine registram tarefas
# ``test:*`` dentro das funções, então não contaminam este retrato.
load_tasks()
_CATALOG = {spec.name: spec for spec in all_tasks()}

# nome -> (intent, required, optional), exatamente como registrado hoje.
EXPECTED = {
    "audit:removal": ("write", ["target"], ["kind", "matcher", "write", "json"]),
    "audit:verify": ("read", [], ["ledger", "fail_on_leftovers", "json"]),
    "clean:artifacts": ("write", [], ["scope", "dry_run"]),
    "clean:runs": ("write", [], ["days", "keep", "dry_run"]),
    "code:brief": (
        "read",
        [],
        ["path", "table", "symbol", "dir", "changed", "mode", "budget", "max_paths", "max_tables", "json"],
    ),
    "code:outline": ("read", ["file"], []),
    "code:read": ("read", ["file"], ["start", "end", "max_lines"]),
    "code:search": ("read", ["pattern"], ["path", "glob", "max_results", "scope"]),
    "code:skeleton": (
        "read",
        [],
        ["full", "level", "path", "exclude", "split_map", "map_part_chars", "part"],
    ),
    "code:symbol": ("read", ["name"], ["kind", "max_results"]),
    "context:pack": ("read", ["files"], ["ranges", "budget"]),
    "db:links": ("read", [], ["file", "table", "max_file_mb"]),
    "db:query": ("read", ["sql"], ["limit"]),
    "db:schema": ("read", ["table"], []),
    "db:snapshot": ("read", [], ["source"]),
    "docker:exec": ("write", ["container", "command"], ["timeout"]),
    "docs:import": ("read", [], ["source", "kind"]),
    "env:check": ("read", [], []),
    "file:read": ("read", ["path"], ["start", "end"]),
    "git:run": ("read", ["args"], ["repo"]),
    "graph:export": ("write", [], ["format", "out"]),
    "graph:stats": ("read", [], ["json"]),
    "knowledge:verify": ("read", [], ["deep", "fail_on_dirty", "json"]),
    "lint": ("read", [], ["filter"]),
    "logs:tail": ("read", ["container"], ["lines"]),
    "patch:apply": ("write", ["diff"], ["verify", "branch", "allow_dirty", "strip"]),
    "prompt": ("read", [], []),
    "py:run": ("write", [], ["script", "module", "args", "cwd"]),
    "rag:search": ("read", ["query"], ["doc_type", "top_k", "source_kind"]),
    "rag:serve": ("read", [], ["action", "host", "port", "timeout"]),
    "rag:sync": ("read", [], ["full"]),
    "shell:run": ("write", ["command"], ["shell", "cwd"]),
    "state:list": ("read", [], []),
    "state:load": ("read", [], ["name", "last"]),
    "state:save": ("write", [], ["content", "file", "clip"]),
    "test:run": ("read", [], ["filter"]),
    "verify": ("read", [], ["filter"]),
    "watch:clip": ("read", [], ["interval_ms", "stop", "max_cycles"]),
    "watch:downloads": (
        "read",
        [],
        ["path", "interval_ms", "stop", "max_cycles", "branch", "include_existing"],
    ),
}

# Dono alvo de cada tarefa no desmembramento. Ainda não existe no código;
# este mapa é a referência que a fase D0 vai implementar.
OWNER = {
    "audit:removal": "harness",
    "audit:verify": "harness",
    "clean:artifacts": "harness_clean",
    "clean:runs": "harness_clean",
    "code:brief": "harness",
    "code:outline": "harness",
    "code:read": "harness",
    "code:search": "harness",
    "code:skeleton": "harness",
    "code:symbol": "harness",
    "context:pack": "harness",
    "db:links": "harness",
    "db:query": "harness",
    "db:schema": "harness",
    "db:snapshot": "harness",
    "docker:exec": "harness_exec",
    "docs:import": "harness",
    "env:check": "core",
    "file:read": "harness",
    "git:run": "harness_exec",
    "graph:export": "harness",
    "graph:stats": "harness",
    "knowledge:verify": "harness",
    "lint": "harness_validate",
    "logs:tail": "harness_exec",
    "patch:apply": "harness_patch",
    "prompt": "core",
    "py:run": "harness_exec",
    "rag:search": "harness",
    "rag:serve": "harness",
    "rag:sync": "harness",
    "shell:run": "harness_exec",
    "state:list": "harness_state",
    "state:load": "harness_state",
    "state:save": "harness_state",
    "test:run": "harness_validate",
    "verify": "harness_validate",
    "watch:clip": "harness_watch",
    "watch:downloads": "harness_watch",
}

PACKS = {
    "harness",
    "harness_exec",
    "harness_patch",
    "harness_validate",
    "harness_state",
    "harness_watch",
    "harness_clean",
    "core",
}

# Hash de EXPECTED (nome -> [intent, required, optional]). Qualquer mudança de
# assinatura exige atualizar este valor de forma explícita.
CONTRACT_SHA256 = "48e555576a3c6e422fe285e2db318a202ad4159d1c3ee5172ef956a55924389f"


def _catalog():
    return _CATALOG


def test_inventory_count():
    assert len(_catalog()) == 39


def test_inventory_matches_frozen_names():
    assert set(_catalog()) == set(EXPECTED)


def test_signatures_are_frozen():
    catalog = _catalog()
    for name, (intent, required, optional) in EXPECTED.items():
        spec = catalog[name]
        assert (spec.intent, spec.required, spec.optional) == (
            intent,
            required,
            optional,
        ), name


def test_owner_map_covers_every_task():
    assert set(OWNER) == set(EXPECTED)
    assert set(OWNER.values()) <= PACKS


def test_target_pack_distribution():
    assert Counter(OWNER.values()) == {
        "harness": 21,
        "harness_exec": 5,
        "harness_patch": 1,
        "harness_validate": 3,
        "harness_state": 3,
        "harness_watch": 2,
        "harness_clean": 2,
        "core": 2,
    }


def test_manifest_owner_map_matches_frozen_owner():
    assert packs.owner_map() == OWNER


def test_task_spec_pack_matches_owner():
    for name, spec in _catalog().items():
        assert spec.pack == OWNER[name], name


def test_owner_of_representative_tasks():
    assert packs.owner_of("shell:run") == "harness_exec"
    assert packs.owner_of("env:check") == "core"
    assert packs.owner_of("code:search") == "harness"
    assert packs.owner_of("patch:apply") == "harness_patch"
    assert packs.owner_of("inexistente") is None


def test_duplicate_owner_is_rejected():
    with pytest.raises(ValueError, match="tarefa duplicada: x"):
        packs.build_owner([("a", ["x"]), ("b", ["x"])])


def test_contract_hash_is_stable():
    payload = json.dumps(
        {name: list(signature) for name, signature in EXPECTED.items()},
        sort_keys=True,
        ensure_ascii=False,
    )
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == CONTRACT_SHA256


def test_plugin_enabled_default_and_disabled():
    assert packs.is_enabled({}, "harness_exec")
    assert packs.is_enabled({"plugins": {"exec": {"enabled": True}}}, "harness_exec")
    assert not packs.is_enabled({"plugins": {"exec": {"enabled": False}}}, "harness_exec")
