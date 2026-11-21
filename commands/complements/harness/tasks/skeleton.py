"""Tarefa code:skeleton — mapa leve do sistema legado.

Gera, em uma única passada (incremental por mtime/tamanho):

* ``workspace/knowledge/skeleton/project.json`` — diretórios, arquivos,
  símbolos com intervalo de linhas, tabelas SQL citadas e imports;
* ``workspace/knowledge/skeleton/SKELETON.md`` — resumo compacto para injetar
  no prompt do LLM (orçamento fixo, truncando com aviso).

Nada é copiado do repositório legado: o índice aponta para os arquivos reais.
"""

import json
import os
import re
import time
from datetime import datetime

from .. import astsym
from ..catalog import register
from ..filters import CODE_EXTENSIONS, iter_files, relative
from ..task_types import TaskResult, TaskSpec
from ..util import as_bool, ensure_dir, legacy_repo, read_text, workspace, write_json, write_text

# Orçamento do Markdown que vai para o prompt (o JSON pode ser maior).
SKELETON_BUDGET = 40_000
# Acima disso o arquivo não é parseado em busca de símbolos.
MAX_PARSE_BYTES = 2 * 1024 * 1024

TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|REPLACE\s+INTO)\s+[`\"']?([A-Za-z_][\w$]*)",
    re.IGNORECASE,
)
IMPORT_RE = re.compile(
    r"^\s*(?:include|include_once|require|require_once|import|from)\b[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
_SQL_WORDS = {
    "select",
    "where",
    "set",
    "values",
    "dual",
    "table",
    "as",
    "on",
    "using",
    "group",
    "order",
    "limit",
    "into",
}


def skeleton_dir(ctx) -> str:
    return ensure_dir(os.path.join(workspace(ctx), "knowledge", "skeleton"))


def project_path(ctx) -> str:
    return os.path.join(skeleton_dir(ctx), "project.json")


# ---------------------------------------------------------------------------
# Extração por arquivo
# ---------------------------------------------------------------------------
def _tables(text: str) -> list[str]:
    found = set()
    for match in TABLE_RE.finditer(text):
        name = match.group(1)
        if not name or name.startswith("$") or name.lower() in _SQL_WORDS:
            continue
        found.add(name)
    return sorted(found)


def _imports(text: str) -> list[str]:
    values = []
    for match in IMPORT_RE.finditer(text):
        line = match.group(0).strip()
        if line and line not in values:
            values.append(line[:160])
    return values[:40]


def _entry(path: str, repo: str) -> dict:
    size = os.path.getsize(path)
    try:
        text = read_text(path)
    except OSError:
        text = ""

    return {
        "loc": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        "mtime": int(os.path.getmtime(path)),
        "size": size,
        "symbols": astsym.definitions(text, path) if size <= MAX_PARSE_BYTES else [],
        "tables": _tables(text),
        "imports": _imports(text),
    }


def _load_previous(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# SKELETON.md
# ---------------------------------------------------------------------------
def _dir_counts(files_index: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relative_path in files_index:
        directory = os.path.dirname(relative_path)
        key = directory or "."
        counts[key] = counts.get(key, 0) + 1
    return counts


def _render(files_index: dict, tables: dict, repo: str, generated_at: str, symbols_per_file: int) -> str:
    dirs = _dir_counts(files_index)
    symbols = sum(len(entry.get("symbols") or []) for entry in files_index.values())
    loc = sum(int(entry.get("loc") or 0) for entry in files_index.values())

    parts = [
        f"# Esqueleto: {os.path.basename(repo.rstrip(os.sep)) or repo}",
        "",
        f"- repo: `{repo}`",
        f"- arquivos: {len(files_index)} | linhas: {loc} | símbolos: {symbols} | tabelas: {len(tables)}",
        f"- gerado em: {generated_at}",
        "",
        "## Diretórios",
        "",
    ]
    for directory, count in sorted(dirs.items()):
        parts.append(f"- `{directory}/` ({count} arquivo(s))")

    if tables:
        parts.extend(["", f"## Tabelas ({len(tables)})", ""])
        ranked = sorted(
            tables.items(), key=lambda item: (-len(item[1]), item[0])
        )
        for table, files in ranked:
            listed = ", ".join(f"`{name}`" for name in files[:3])
            extra = f" +{len(files) - 3}" if len(files) > 3 else ""
            parts.append(f"- `{table}`: {listed}{extra}")

    parts.extend(["", "## Símbolos por diretório", ""])
    by_dir: dict[str, list[tuple[str, dict]]] = {}
    for relative_path, entry in files_index.items():
        directory = os.path.dirname(relative_path) or "."
        by_dir.setdefault(directory, []).append((relative_path, entry))

    for directory in sorted(by_dir):
        parts.append(f"### {directory}/")
        parts.append("")
        for relative_path, entry in sorted(by_dir[directory]):
            name = os.path.basename(relative_path)
            items = entry.get("symbols") or []
            shown = items[:symbols_per_file]
            labels = ", ".join(
                f"`{item['name']}` (L{item['line']})" for item in shown
            )
            suffix = f" +{len(items) - len(shown)}" if len(items) > len(shown) else ""
            parts.append(f"- `{name}` ({entry.get('loc', 0)} LOC): {labels}{suffix}")
        parts.append("")

    parts.extend(
        [
            "## Como navegar",
            "",
            "1. `code:search pattern=\"...\" path=<diretório>` para localizar.",
            "2. `code:read file=<arquivo> start=<linha>` para ler o trecho.",
            "3. `code:symbol name=<símbolo> kind=ref` para ver quem chama.",
            "",
        ]
    )
    return "\n".join(parts)


def _fit(files_index: dict, tables: dict, repo: str, generated_at: str) -> tuple[str, int]:
    """Reduz a quantidade de símbolos por arquivo até caber no orçamento."""
    for symbols_per_file in (12, 6, 3, 0):
        text = _render(files_index, tables, repo, generated_at, symbols_per_file)
        if len(text) <= SKELETON_BUDGET:
            return text, symbols_per_file

    text = _render(files_index, tables, repo, generated_at, 0)
    return (
        text[:SKELETON_BUDGET]
        + "\n\n(truncado) esqueleto maior que o orçamento; use `code:outline`/`code:search`.\n",
        0,
    )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def handle(ctx, params):
    repo = legacy_repo(ctx)
    if not os.path.isdir(repo):
        return TaskResult(False, f"repositório não encontrado: {repo}", exit_code=2)

    full = as_bool(params.get("full"))
    target = project_path(ctx)
    previous = {} if full else _load_previous(target)
    previous_files = previous.get("files_index") or {}

    files_index: dict[str, dict] = {}
    reused = 0
    skipped: dict = {}
    started = time.time()

    for path in iter_files(repo, CODE_EXTENSIONS, skipped=skipped):
        relative_path = relative(repo, path)
        try:
            size = os.path.getsize(path)
            mtime = int(os.path.getmtime(path))
        except OSError:
            continue

        cached = previous_files.get(relative_path)
        if (
            cached
            and cached.get("mtime") == mtime
            and cached.get("size") == size
            and size <= MAX_PARSE_BYTES
        ):
            files_index[relative_path] = cached
            reused += 1
            continue

        files_index[relative_path] = _entry(path, repo)

    tables: dict[str, list[str]] = {}
    for relative_path, entry in files_index.items():
        for table in entry.get("tables") or []:
            tables.setdefault(table, []).append(relative_path)
    for name in tables:
        tables[name] = sorted(set(tables[name]))

    generated_at = datetime.now().isoformat(timespec="seconds")
    elapsed = time.time() - started

    data = {
        "version": 1,
        "repo": repo,
        "generated_at": generated_at,
        "extensions": sorted(CODE_EXTENSIONS),
        "files": len(files_index),
        "loc": sum(int(entry.get("loc") or 0) for entry in files_index.values()),
        "symbols": sum(len(entry.get("symbols") or []) for entry in files_index.values()),
        "dirs": sorted(_dir_counts(files_index)),
        "tables": tables,
        "files_index": files_index,
        "skipped": skipped,
    }

    write_json(target, data)
    markdown, symbols_per_file = _fit(files_index, tables, repo, generated_at)
    skeleton_md = os.path.join(skeleton_dir(ctx), "SKELETON.md")
    write_text(skeleton_md, markdown)

    summary = (
        f"{len(files_index)} arquivo(s), {data['symbols']} símbolo(s), "
        f"{len(tables)} tabela(s) em {elapsed:.1f}s"
    )
    if reused:
        summary += f" ({reused} reaproveitado(s))"

    details = [
        f"project.json: {target} ({os.path.getsize(target)} bytes)",
        f"SKELETON.md: {skeleton_md} ({len(markdown)} bytes, {symbols_per_file} símbolo(s)/arquivo)",
    ]
    if skipped.get("build_artifacts"):
        details.append(f"{skipped['build_artifacts']} bundle(s) minificado(s) ignorado(s)")
    if skipped.get("large_files"):
        details.append(f"{skipped['large_files']} arquivo(s) grande(s) ignorado(s)")

    return TaskResult(
        True,
        summary,
        details="\n".join(details),
        artifacts=[target, skeleton_md],
    )


register(
    TaskSpec(
        name="code:skeleton",
        intent="read",
        description="Gera o esqueleto do código (símbolos, tabelas, imports) sem copiar fontes",
        required=[],
        optional=["full"],
        handler=handle,
    )
)
