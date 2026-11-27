"""Layout do harness_core: sem sombra de stdlib e sem importar handlers de pack."""

import os
import sys

CORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "commands",
    "complements",
    "harness_core",
)


def _modules():
    for entry in os.listdir(CORE):
        path = os.path.join(CORE, entry)
        if os.path.isfile(path) and entry.endswith(".py"):
            yield path


def test_core_does_not_shadow_stdlib():
    stdlib = set(sys.stdlib_module_names)
    clashes = sorted(
        os.path.basename(path)
        for path in _modules()
        if os.path.basename(path)[:-3] in stdlib
    )
    assert clashes == []


def test_core_does_not_import_pack_handlers():
    forbidden = ("harness.tasks", "from ..harness", "from .harness")
    for path in _modules():
        text = open(path, encoding="utf-8").read()
        for needle in forbidden:
            assert needle not in text, f"{os.path.basename(path)}: {needle}"


def test_paths_point_to_harness_home():
    from commands.complements.harness_core import paths

    assert paths.HARNESS_HOME.name == "harness"
    assert paths.HARNESS_HOME.parent.name == "complements"
    assert paths.WORKSPACE.name == "workspace"
