"""Inventário congelado das tarefas e mapa de donos (B0.2).

Este teste é o contrato do desmembramento: nenhuma tarefa pode sumir, mudar de
assinatura ou de dono sem uma atualização explícita. A R0.2 removeu as três tarefas
`notes:*` (34 restantes); a R0.3 remove `kb:export` (33) e a R0.12 finaliza o mapa.
"""

from collections import Counter

from commands.complements.harness.catalog import all_tasks, load_tasks

# Snapshot limpo no import do módulo: os testes de engine registram tarefas
# ``test:*`` dentro das funções, então não contaminam este retrato.
load_tasks()
_CATALOG = {spec.name: spec for spec in all_tasks()}

# nome -> (intent, required, optional), exatamente como registrado hoje.
EXPECTED = {
    "clean:artifacts": ("write", [], ["scope", "dry_run"]),
    "clean:runs": ("write", [], ["days", "keep", "dry_run"]),
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
    "kb:export": ("write", [], ["out", "max_chars"]),
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
    "clean:artifacts": "harness_clean",
    "clean:runs": "harness_clean",
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
    "kb:export": "harness",
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


def _catalog():
    return _CATALOG


def test_inventory_count():
    assert len(_catalog()) == 34


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
        "harness": 16,
        "harness_exec": 5,
        "harness_patch": 1,
        "harness_validate": 3,
        "harness_state": 3,
        "harness_watch": 2,
        "harness_clean": 2,
        "core": 2,
    }
