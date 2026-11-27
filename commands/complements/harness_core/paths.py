"""Caminhos compartilhados do harness (workspace, venv e home)."""

import os
from pathlib import Path

COMPLEMENTS = Path(__file__).resolve().parent.parent
HARNESS_HOME = Path(os.environ.get("HARNESS_HOME", COMPLEMENTS / "harness"))
WORKSPACE = Path(os.environ.get("HARNESS_WORKSPACE", HARNESS_HOME / "workspace"))
VENV = HARNESS_HOME / ".venv"
