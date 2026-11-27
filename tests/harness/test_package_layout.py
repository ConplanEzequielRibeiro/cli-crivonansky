"""Guarda-corpo de layout: nenhum módulo do plugin pode sombrear a stdlib.

O plugin já teve um ``types.py``; quando o diretório do harness entrava no
``sys.path`` (subprocessos, builds do pip, execução a partir da pasta), o
``import types`` resolvia para o módulo do plugin e quebrava ferramentas que
esperam ``types.ModuleType``. O ``task_types.py`` vive no ``harness_core`` desde D1.
"""

import os
import sys

COMPLEMENTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "commands",
    "complements",
)
HARNESS = os.path.join(COMPLEMENTS, "harness")
CORE = os.path.join(COMPLEMENTS, "harness_core")


def _top_level_modules(folder):
    for entry in os.listdir(folder):
        path = os.path.join(folder, entry)
        if os.path.isfile(path) and entry.endswith(".py"):
            yield path, entry[: -len(".py")]


def test_types_module_was_renamed():
    assert not os.path.exists(os.path.join(HARNESS, "types.py"))
    assert not os.path.exists(os.path.join(CORE, "types.py"))
    assert os.path.exists(os.path.join(CORE, "task_types.py"))


def test_no_harness_module_shadows_stdlib():
    stdlib = set(sys.stdlib_module_names)
    clashes = []
    for folder in (HARNESS, CORE):
        clashes.extend(
            os.path.relpath(path, folder)
            for path, name in _top_level_modules(folder)
            if name in stdlib
        )
    assert clashes == []
