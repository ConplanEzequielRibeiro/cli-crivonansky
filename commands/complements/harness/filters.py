"""Filtros de varredura do repositório legado.

Centraliza o recorte de diretórios/arquivos ignorados para que o esqueleto
(`code:skeleton`), a busca JIT (`code:search`) e o `db:links` enxerguem
exatamente o mesmo conjunto de arquivos.
"""

import os
import re

# Terceiros, artefatos de build e metadados de VCS.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "vendor",
    "node_modules",
    ".venv",
    "venv",
    "site-packages",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "coverage",
}

# Fontes que o harness analisa (SQL embutido, símbolos, esqueleto).
CODE_EXTENSIONS = {".php", ".js", ".ts", ".jsx", ".tsx", ".py"}

# Bundles/minificados não são escritos à mão; ignorá-los evita gastar tempo.
ARTIFACT_RE = re.compile(r"\.(?:min|bundle|pack)\.js$", re.I)


def iter_files(
    root: str,
    extensions: set[str] | None = None,
    max_bytes: int = 0,
    skipped: dict | None = None,
):
    """Percorre ``root`` devolvendo apenas fontes de código (sem terceiros).

    ``skipped`` (opcional) acumula contadores usados nos relatórios das tarefas.
    """
    skipped = skipped if skipped is not None else {}
    wanted = extensions or CODE_EXTENSIONS

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name.lower() not in SKIP_DIRS)

        for filename in sorted(filenames):
            extension = os.path.splitext(filename)[1].lower()
            if extension not in wanted:
                continue
            if ARTIFACT_RE.search(filename):
                skipped["build_artifacts"] = skipped.get("build_artifacts", 0) + 1
                continue

            path = os.path.join(dirpath, filename)
            if max_bytes:
                try:
                    if os.path.getsize(path) > max_bytes:
                        skipped["large_files"] = skipped.get("large_files", 0) + 1
                        continue
                except OSError:
                    continue
            yield path


def relative(root: str, path: str) -> str:
    """Caminho relativo com separador ``/`` (portável em JSON/Markdown)."""
    return os.path.relpath(path, root).replace("\\", "/")
