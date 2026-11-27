"""Plugin harness do crivonansky.

As dependências externas (PyYAML, pyperclip, sqlglot, ast-grep-py) ficam no venv
do próprio plugin. O bootstrap abaixo torna esse venv visível ao interpretador
do crivonansky sem exigir instalação no venv do host.
"""

from ..harness_core.bootstrap import ensure_deps

ensure_deps()
