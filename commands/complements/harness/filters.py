"""Filtros de varredura do repositório legado.

Centraliza o recorte de diretórios/arquivos ignorados para que o esqueleto
(`code:skeleton`), a busca JIT (`code:search`) e o `db:links` enxerguem
exatamente o mesmo conjunto de arquivos.
"""

import fnmatch
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


def config_excludes(config: dict | None, extra=None) -> list[str]:
    """Padrões de exclusão: ``legacy.exclude`` da config + ``extra`` (parâmetro)."""
    from commands.complements.harness_core.util import as_list

    legacy = (config or {}).get("legacy") or {}
    patterns = [str(item) for item in as_list(legacy.get("exclude"))]
    patterns += [str(item) for item in as_list(((config or {}).get("skeleton") or {}).get("exclude"))]
    patterns += [str(item) for item in as_list(extra)]
    return [item.replace("\\", "/").strip("/") for item in patterns if item]


def is_excluded(rel_path: str, patterns: list[str]) -> bool:
    """Casa ``rel_path`` (``/``) com globs de caminho, de nome ou de diretório.

    ``legado/*`` ou ``relatorios`` excluem a árvore; ``*.bak.php`` exclui por nome.
    """
    if not patterns:
        return False
    rel_path = rel_path.replace("\\", "/").strip("/")
    name = rel_path.rsplit("/", 1)[-1]
    for pattern in patterns:
        if (
            fnmatch.fnmatch(rel_path, pattern)
            or fnmatch.fnmatch(name, pattern)
            or rel_path.startswith(pattern + "/")
            or fnmatch.fnmatch(rel_path, pattern + "/*")
        ):
            return True
    return False


def iter_files(
    root: str,
    extensions: set[str] | None = None,
    max_bytes: int = 0,
    skipped: dict | None = None,
    exclude: list[str] | None = None,
):
    """Percorre ``root`` devolvendo apenas fontes de código (sem terceiros).

    ``skipped`` (opcional) acumula contadores usados nos relatórios das tarefas.
    ``exclude`` são globs (ver ``is_excluded``) para podar diretórios/arquivos.
    """
    skipped = skipped if skipped is not None else {}
    wanted = extensions or CODE_EXTENSIONS
    exclude = exclude or []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name.lower() not in SKIP_DIRS
            and not (exclude and is_excluded(relative(root, os.path.join(dirpath, name)), exclude))
        )

        for filename in sorted(filenames):
            extension = os.path.splitext(filename)[1].lower()
            if extension not in wanted:
                continue
            if ARTIFACT_RE.search(filename):
                skipped["build_artifacts"] = skipped.get("build_artifacts", 0) + 1
                continue

            path = os.path.join(dirpath, filename)
            if exclude and is_excluded(relative(root, path), exclude):
                skipped["excluded"] = skipped.get("excluded", 0) + 1
                continue
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
