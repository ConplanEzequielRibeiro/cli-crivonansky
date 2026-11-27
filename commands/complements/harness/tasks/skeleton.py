"""Tarefa code:skeleton — mapa leve do sistema legado.

Gera, em uma única passada (incremental por mtime/tamanho):

* ``workspace/knowledge/skeleton/project.json`` — diretórios, arquivos,
  símbolos com intervalo de linhas, tabelas SQL citadas e imports;
* ``workspace/knowledge/skeleton/SKELETON.md`` — índice compacto para injetar
  no prompt do LLM; em repositórios pequenos traz os símbolos inline, nos grandes
  vira só diretórios + tabelas + ponteiros (nunca corta no meio);
* ``workspace/knowledge/skeleton/MAP.md`` — por diretório, os arquivos mais
  relevantes (ranking por tabelas, símbolos, tamanho e quem os inclui); com
  ``split_map`` (ou ``skeleton.map_split``) vira o mapa completo, dividido em
  ``map/part-NNN.md`` + um índice quando passa do orçamento;
* ``workspace/knowledge/skeleton/dirs/<dir>.md`` — fatia detalhada de cada
  diretório, lida sob demanda (``level=dir path=<dir>``).

Nada é copiado do repositório legado: o índice aponta para os arquivos reais.
"""

import json
import os
import re
import time
from datetime import datetime

from .. import astsym
from commands.complements.harness_core.catalog import register
from ..filters import config_excludes, iter_files, relative
from commands.complements.harness_core.formatter import cut_head
from commands.complements.harness_core.runner import run_process
from ..profiles import resolve_profile
from commands.complements.harness_core.task_types import TaskResult, TaskSpec
from commands.complements.harness_core.util import (
    as_bool,
    as_int,
    as_list,
    ensure_dir,
    legacy_repo,
    read_text,
    workspace,
    write_json,
    write_text,
)

# Orçamento do SKELETON.md (vai para o prompt) e do MAP.md; o JSON pode ser maior.
SKELETON_BUDGET = 16_000
MAP_BUDGET = 24_000
# O mapa completo (mapa dividido) nunca corta: cada parte respeita este orçamento.
MAP_PART_BUDGET = 24_000
# Arquivos de destaque por diretório no MAP.md e tabelas no índice.
MAP_TOP_FILES = 5
INDEX_TOP_TABLES = 40
MAP_PARTS_DIR = "map"
LEVELS = ("index", "map", "dir", "part")
# Versão do ``project.json``: invalida o cache incremental quando o parser muda.
PROJECT_VERSION = 3
# Acima disso o arquivo não é parseado em busca de símbolos.
MAX_PARSE_BYTES = 2 * 1024 * 1024

TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|REPLACE\s+INTO)\s+[`\"']?([A-Za-z_][\w$]*)",
    re.IGNORECASE,
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


def _imports(text: str, path: str, profile) -> list[str]:
    return astsym.extract_imports(text, path, profile.import_patterns)


def _entry(path: str, repo: str, profile) -> dict:
    size = os.path.getsize(path)
    try:
        text = read_text(path, profile.encoding)
    except OSError:
        text = ""

    return {
        "loc": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        "mtime": int(os.path.getmtime(path)),
        "size": size,
        "symbols": (
            astsym.definitions(text, path, profile.languages, profile.definition_kinds)
            if size <= MAX_PARSE_BYTES
            else []
        ),
        "tables": _tables(text),
        "imports": _imports(text, path, profile),
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


def _by_dir(files_index: dict) -> dict[str, list[tuple[str, dict]]]:
    grouped: dict[str, list[tuple[str, dict]]] = {}
    for relative_path, entry in files_index.items():
        directory = os.path.dirname(relative_path) or "."
        grouped.setdefault(directory, []).append((relative_path, entry))
    for items in grouped.values():
        items.sort()
    return grouped


def slice_name(directory: str) -> str:
    """Nome do arquivo de fatia de um diretório (``a/b`` → ``a__b``)."""
    if directory in (".", ""):
        return "_raiz"
    return re.sub(r"[^\w.-]+", "__", directory.strip("/"))


def _header(files_index: dict, tables: dict, repo: str, generated_at: str, label: str) -> list[str]:
    symbols = sum(len(entry.get("symbols") or []) for entry in files_index.values())
    loc = sum(int(entry.get("loc") or 0) for entry in files_index.values())
    return [
        f"# Esqueleto: {os.path.basename(repo.rstrip(os.sep)) or repo}",
        "",
        f"- repo: `{repo}`",
        f"- stack: {label}",
        f"- arquivos: {len(files_index)} | linhas: {loc} | símbolos: {symbols} | tabelas: {len(tables)}",
        f"- gerado em: {generated_at}",
        "",
    ]


def _table_lines(tables: dict, limit: int | None = None) -> list[str]:
    ranked = sorted(tables.items(), key=lambda item: (-len(item[1]), item[0]))
    shown = ranked if limit is None else ranked[:limit]
    lines = []
    for table, files in shown:
        listed = ", ".join(f"`{name}`" for name in files[:3])
        extra = f" +{len(files) - 3}" if len(files) > 3 else ""
        lines.append(f"- `{table}`: {listed}{extra}")
    if limit is not None and len(ranked) > limit:
        lines.append(f"- … +{len(ranked) - limit} tabela(s); veja `project.json` ou `code:skeleton level=map`.")
    return lines


def _symbol_lines(dir_files: list[tuple[str, dict]], symbols_per_file: int) -> list[str]:
    lines = []
    for relative_path, entry in dir_files:
        name = os.path.basename(relative_path)
        items = entry.get("symbols") or []
        shown = items[:symbols_per_file]
        labels = ", ".join(f"`{item['name']}` (L{item['line']})" for item in shown)
        suffix = f" +{len(items) - len(shown)}" if len(items) > len(shown) else ""
        lines.append(f"- `{name}` ({entry.get('loc', 0)} LOC): {labels}{suffix}")
    return lines


NAVIGATE = [
    "## Como navegar",
    "",
    "1. `code:skeleton level=map` para os arquivos mais relevantes por diretório.",
    "2. `code:skeleton level=dir path=<diretório>` para os símbolos de um diretório.",
    "3. `code:skeleton level=part part=<N>` para uma parte do mapa completo (se houver).",
    "4. `code:search pattern=\"...\" path=<diretório>` para localizar.",
    "5. `code:read file=<arquivo> start=<linha>` para ler o trecho.",
    "6. `code:symbol name=<símbolo> kind=ref` para ver quem chama.",
    "",
]


def _render(
    files_index: dict,
    tables: dict,
    repo: str,
    generated_at: str,
    symbols_per_file: int,
    label: str,
) -> str:
    """Versão completa (índice + símbolos inline): para repositórios pequenos."""
    grouped = _by_dir(files_index)
    parts = _header(files_index, tables, repo, generated_at, label)
    parts += ["## Diretórios", ""]
    for directory in sorted(grouped):
        parts.append(f"- `{directory}/` ({len(grouped[directory])} arquivo(s))")

    if tables:
        parts += ["", f"## Tabelas ({len(tables)})", ""]
        parts += _table_lines(tables)

    parts += ["", "## Símbolos por diretório", ""]
    for directory in sorted(grouped):
        parts += [f"### {directory}/", ""]
        parts += _symbol_lines(grouped[directory], symbols_per_file)
        parts.append("")
    parts += NAVIGATE
    return "\n".join(parts)


def _render_index(
    files_index: dict, tables: dict, repo: str, generated_at: str, label: str
) -> str:
    """Índice enxuto: diretórios agregados + tabelas mais usadas + ponteiros."""
    grouped = _by_dir(files_index)
    parts = _header(files_index, tables, repo, generated_at, label)

    # Agrega os diretórios por prefixo, reduzindo a profundidade até caber.
    depth = 4
    rows: list[str] = []
    while True:
        agg: dict[str, list[int]] = {}
        for directory, items in grouped.items():
            key = "/".join(directory.split("/")[:depth]) if directory != "." else "."
            stats = agg.setdefault(key, [0, 0])
            stats[0] += len(items)
            stats[1] += sum(len(entry.get("symbols") or []) for _, entry in items)
        rows = [
            f"- `{key}/` — {files} arquivo(s), {syms} símbolo(s)"
            for key, (files, syms) in sorted(agg.items())
        ]
        if len(rows) <= 120 or depth == 1:
            break
        depth -= 1

    parts += [f"## Diretórios ({len(rows)}, profundidade {depth})", ""] + rows
    if tables:
        parts += ["", f"## Tabelas ({len(tables)})", ""]
        parts += _table_lines(tables, INDEX_TOP_TABLES)
    parts += [""]
    parts += [
        "> Índice resumido: os símbolos ficam em `dirs/<diretório>.md` e no `MAP.md`.",
        "",
    ]
    parts += NAVIGATE
    return "\n".join(parts)


def _inbound(files_index: dict) -> dict[str, int]:
    """Quantos arquivos citam (include/import) o nome de cada arquivo."""
    by_name: dict[str, list[str]] = {}
    for relative_path in files_index:
        by_name.setdefault(os.path.basename(relative_path).lower(), []).append(relative_path)

    counts: dict[str, int] = {}
    for source, entry in files_index.items():
        seen: set[str] = set()
        for statement in entry.get("imports") or []:
            for token in re.findall(r"[\w./\\-]+\.\w+", str(statement)):
                base = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
                for candidate in by_name.get(base, []):
                    if candidate != source:
                        seen.add(candidate)
        for candidate in seen:
            counts[candidate] = counts.get(candidate, 0) + 1
    return counts


def recent_commits(repo: str, days: int = 180) -> dict[str, int]:
    """Commits recentes por arquivo (``git log``); vazio se não houver git."""
    if days <= 0 or not os.path.isdir(os.path.join(repo, ".git")):
        return {}
    result = run_process(
        ["git", "log", f"--since={int(days)}.days", "--name-only", "--pretty=format:"],
        cwd=repo,
        timeout=60,
    )
    if result.exit_code != 0:
        return {}
    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        line = line.strip().replace("\\", "/")
        if line:
            counts[line] = counts.get(line, 0) + 1
    return counts


def rank_files(files_index: dict, recent: dict | None = None) -> dict[str, float]:
    """Relevância: tabelas, includes recebidos, símbolos, tamanho e commits recentes."""
    recent = recent or {}
    inbound = _inbound(files_index)
    scores: dict[str, float] = {}
    for relative_path, entry in files_index.items():
        scores[relative_path] = (
            3 * len(entry.get("tables") or [])
            + 2 * inbound.get(relative_path, 0)
            + len(entry.get("symbols") or [])
            + min(int(entry.get("loc") or 0), 2000) / 200
            + 1.5 * min(recent.get(relative_path, 0), 10)
        )
    return scores


def _map_header(generated_at: str, top: int | None) -> list[str]:
    scope = f"os {top} arquivos mais relevantes" if top else "todos os arquivos"
    return [
        "# Mapa do código",
        "",
        f"- gerado em: {generated_at}",
        f"- por diretório, {scope} (`sím` = símbolos, `tab` = tabelas citadas)",
        "",
    ]


def _map_sections(
    files_index: dict, scores: dict[str, float], top: int | None
) -> list[tuple[str, list[str]]]:
    """Blocos Markdown por diretório (``top=None`` inclui todos os arquivos)."""
    grouped = _by_dir(files_index)
    sections: list[tuple[str, list[str]]] = []
    for directory in sorted(grouped):
        items = grouped[directory]
        ranked = sorted(items, key=lambda item: (-scores[item[0]], item[0]))
        shown = ranked if top is None else ranked[:top]
        lines = [f"## {directory}/ ({len(items)})", ""]
        for relative_path, entry in shown:
            tabs = entry.get("tables") or []
            extra = f", tab: {', '.join(tabs[:3])}" if tabs else ""
            lines.append(
                f"- `{os.path.basename(relative_path)}` {entry.get('loc', 0)}L, "
                f"{len(entry.get('symbols') or [])} sím{extra}"
            )
        if top is not None and len(items) > top:
            lines.append(f"- … +{len(items) - top} arquivo(s)")
        lines.append("")
        sections.append((directory, lines))
    return sections


def _render_map(
    files_index: dict,
    tables: dict,
    generated_at: str,
    recent: dict | None = None,
    top: int | None = MAP_TOP_FILES,
) -> str:
    scores = rank_files(files_index, recent)
    parts = _map_header(generated_at, top)
    for _directory, lines in _map_sections(files_index, scores, top):
        parts += lines
    return "\n".join(parts)


def _render_slice(directory: str, items: list[tuple[str, dict]]) -> str:
    parts = [f"# {directory}/ ({len(items)} arquivo(s))", ""]
    parts += _symbol_lines(items, 10_000)
    parts.append("")
    return "\n".join(parts)


def _fit_text(text: str, budget: int, hint: str) -> str:
    """Corta em fronteira de linha com marcador explícito se passar do orçamento."""
    if len(text) <= budget:
        return text
    cut, _omitted = cut_head(text, budget, hint=hint)
    return cut


def _fit(
    files_index: dict,
    tables: dict,
    repo: str,
    generated_at: str,
    label: str,
    max_symbols: int = 12,
) -> tuple[str, int]:
    """SKELETON.md: completo se couber; senão, índice enxuto (nunca cortado ao meio)."""
    steps = [max_symbols] + [n for n in (12, 6, 3) if n < max_symbols]
    for symbols_per_file in steps:
        text = _render(files_index, tables, repo, generated_at, symbols_per_file, label)
        if len(text) <= SKELETON_BUDGET:
            return text, symbols_per_file

    text = _render_index(files_index, tables, repo, generated_at, label)
    return (
        _fit_text(
            text,
            SKELETON_BUDGET,
            "Use `code:skeleton level=map` ou `level=dir path=<diretório>`.",
        ),
        0,
    )


def _write_slices(ctx, files_index: dict) -> int:
    folder = os.path.join(skeleton_dir(ctx), "dirs")
    ensure_dir(folder)
    for name in os.listdir(folder):
        if name.endswith(".md"):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
    grouped = _by_dir(files_index)
    for directory, items in grouped.items():
        write_text(
            os.path.join(folder, slice_name(directory) + ".md"),
            _render_slice(directory, items),
        )
    return len(grouped)


# ---------------------------------------------------------------------------
# MAP.md completo: fragmentos + índice (para repositórios grandes)
# ---------------------------------------------------------------------------
def _clear_map_parts(ctx) -> None:
    folder = os.path.join(skeleton_dir(ctx), MAP_PARTS_DIR)
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        if name.endswith(".md"):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


def _split_map_sections(
    sections: list[tuple[str, list[str]]], budget: int
) -> list[dict]:
    """Agrupa os blocos de diretório em partes de até ``budget`` caracteres.

    Uma seção maior que a parte é quebrada em blocos consecutivos (repetindo o
    cabeçalho ``## diretório/``), nunca no meio de uma linha.
    """
    parts: list[dict] = []
    current: dict = {"lines": [], "dirs": [], "files": 0, "chars": 0}
    # Reserva para o cabeçalho de cada parte (título, data e legenda).
    body_budget = max(budget - 400, 500)

    def flush() -> None:
        nonlocal current
        if current["lines"]:
            parts.append(current)
        current = {"lines": [], "dirs": [], "files": 0, "chars": 0}

    def blocks_for(directory: str, lines: list[str]) -> list[list[str]]:
        if len("\n".join(lines)) <= body_budget:
            return [lines]
        header, body = lines[:2], lines[2:]
        chunks: list[list[str]] = []
        chunk: list[str] = []
        size = 0
        for line in body:
            if chunk and size + len(line) + 1 > body_budget:
                chunks.append(chunk)
                chunk, size = [], 0
            chunk.append(line)
            size += len(line) + 1
        if chunk:
            chunks.append(chunk)
        return [header + chunk for chunk in chunks]

    for directory, lines in sections:
        for block in blocks_for(directory, lines):
            block_chars = sum(len(line) + 1 for line in block)
            if current["lines"] and current["chars"] + block_chars > body_budget:
                flush()
            current["lines"] += block
            current["chars"] += block_chars
            current["dirs"].append(directory)
            current["files"] += sum(1 for line in block if line.startswith("- `"))
    flush()
    return parts


def _render_map_index(
    generated_at: str,
    parts: list[dict],
    files_index: dict,
    tables: dict,
    budget: int,
) -> str:
    """Índice do mapa dividido: partes, diretórios e tabelas (sem carregar tudo)."""
    dir_parts: dict[str, list[int]] = {}
    for number, part in enumerate(parts, 1):
        for directory in dict.fromkeys(part["dirs"]):
            dir_parts.setdefault(directory, []).append(number)

    grouped = _by_dir(files_index)
    lines = [
        "# Mapa do código — índice",
        "",
        f"- gerado em: {generated_at}",
        f"- diretórios: {len(grouped)} | arquivos: {len(files_index)} | "
        f"partes: {len(parts)} (até ~{budget} caracteres cada)",
        "- o mapa completo está em `map/part-NNN.md`; carregue só a parte "
        "do diretório que precisar.",
        "",
        "## Partes",
        "",
    ]
    for number, part in enumerate(parts, 1):
        dirs = list(dict.fromkeys(part["dirs"]))
        label = ", ".join(f"`{name}/`" for name in dirs[:6])
        if len(dirs) > 6:
            label += f" +{len(dirs) - 6}"
        lines.append(
            f"- `map/part-{number:03d}.md` — {part['files']} arquivo(s), "
            f"{part['chars']} caracteres: {label or '(vazia)'}"
        )
    lines += ["", f"## Diretórios ({len(grouped)})", ""]
    for directory in sorted(grouped):
        items = grouped[directory]
        syms = sum(len(entry.get("symbols") or []) for _path, entry in items)
        numbers = dir_parts.get(directory) or []
        pointer = ""
        if numbers:
            listed = ", ".join(f"part-{number:03d}.md" for number in numbers[:4])
            if len(numbers) > 4:
                listed += f" +{len(numbers) - 4}"
            pointer = f" → `map/{listed}`"
        lines.append(
            f"- `{directory}/` — {len(items)} arquivo(s), {syms} símbolo(s){pointer}"
        )
    if tables:
        lines += ["", f"## Tabelas ({len(tables)})", ""]
        lines += _table_lines(tables, INDEX_TOP_TABLES)
    lines += [
        "",
        "> Leia uma parte com `code:skeleton level=part part=<N>` "
        "(`path=<diretório>` acha a parte sozinho).",
        "",
    ]
    lines += NAVIGATE
    text = "\n".join(lines)
    if len(text) > budget:
        text = _fit_text(
            text,
            budget,
            "Leia uma parte com `code:skeleton level=part part=<N>`.",
        )
    return text


def _write_map_parts(
    ctx,
    sections: list[tuple[str, list[str]]],
    generated_at: str,
    files_index: dict,
    tables: dict,
    budget: int,
) -> tuple[str, list[str]]:
    """Grava ``map/part-NNN.md`` e devolve ``(índice, caminhos)``."""
    folder = ensure_dir(os.path.join(skeleton_dir(ctx), MAP_PARTS_DIR))
    _clear_map_parts(ctx)
    parts = _split_map_sections(sections, budget)
    total = len(parts)
    paths: list[str] = []
    for number, part in enumerate(parts, 1):
        header = [
            f"# Mapa do código — parte {number}/{total}",
            "",
            f"- gerado em: {generated_at}",
            "- por diretório, todos os arquivos (`sím` = símbolos, `tab` = tabelas citadas)",
            "",
        ]
        path = os.path.join(folder, f"part-{number:03d}.md")
        text = "\n".join(header + part["lines"]).rstrip("\n") + "\n"
        write_text(path, text)
        part["chars"] = len(text)
        paths.append(path)
    index = _render_map_index(generated_at, parts, files_index, tables, budget)
    return index, paths


def _find_part_for_dir(ctx, directory: str) -> str | None:
    """Parte que contém ``directory/`` (ou ``None``)."""
    folder = os.path.join(skeleton_dir(ctx), MAP_PARTS_DIR)
    if not os.path.isdir(folder):
        return None
    header = f"## {directory}/"
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.startswith(header):
                        return path
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def handle(ctx, params):
    repo = legacy_repo(ctx)
    if not os.path.isdir(repo):
        return TaskResult(False, f"repositório não encontrado: {repo}", exit_code=2)

    try:
        profile = resolve_profile(ctx.config)
    except ValueError as exc:
        return TaskResult(False, str(exc), exit_code=2)

    level = str(params.get("level") or "index").strip().lower()
    if level not in LEVELS:
        return TaskResult(
            False, f"level inválido: {level} (use {', '.join(LEVELS)})", exit_code=2
        )
    dir_path = str(params.get("path") or "").replace("\\", "/").strip("/")
    if level == "dir" and not dir_path:
        return TaskResult(False, "level=dir exige o parâmetro 'path'", exit_code=2)

    if level == "part":
        # Lê direto o arquivo já gerado: não reindexa nem apaga as partes.
        part_no = as_int(params.get("part"), 0)
        part_path = None
        if part_no > 0:
            candidate = os.path.join(
                skeleton_dir(ctx), MAP_PARTS_DIR, f"part-{part_no:03d}.md"
            )
            part_path = candidate if os.path.isfile(candidate) else None
        elif dir_path:
            part_path = _find_part_for_dir(ctx, dir_path)
        if part_path is None:
            return TaskResult(
                False,
                "parte do mapa não encontrada",
                hint=(
                    "Informe `part=<N>` (ou `path=<diretório>`); confira as partes em "
                    "`code:skeleton level=map`. O mapa dividido exige "
                    "`split_map=true` (ou `skeleton.map_split: true`)."
                ),
                exit_code=2,
            )
        return TaskResult(
            True,
            f"parte do mapa: {os.path.basename(part_path)}",
            details=read_text(part_path),
            artifacts=[part_path],
            hint="Use `code:skeleton level=dir path=<diretório>` para os símbolos.",
        )

    exclude = config_excludes(ctx.config, params.get("exclude"))
    full = as_bool(params.get("full"))
    target = project_path(ctx)
    previous = {} if full else _load_previous(target)
    # Versão antiga = parser antigo: o cache não vale (símbolos podem estar errados).
    if previous.get("version") != PROJECT_VERSION:
        previous = {}
    previous_files = previous.get("files_index") or {}

    files_index: dict[str, dict] = {}
    reused = 0
    skipped: dict = {}
    started = time.time()

    for path in iter_files(
        repo, profile.code_extensions, skipped=skipped, exclude=exclude
    ):
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

        files_index[relative_path] = _entry(path, repo, profile)

    tables: dict[str, list[str]] = {}
    for relative_path, entry in files_index.items():
        for table in entry.get("tables") or []:
            tables.setdefault(table, []).append(relative_path)
    for name in tables:
        tables[name] = sorted(set(tables[name]))

    generated_at = datetime.now().isoformat(timespec="seconds")
    elapsed = time.time() - started

    data = {
        "version": PROJECT_VERSION,
        "repo": repo,
        "stack": profile.name,
        "generated_at": generated_at,
        "extensions": sorted(profile.code_extensions),
        "files": len(files_index),
        "loc": sum(int(entry.get("loc") or 0) for entry in files_index.values()),
        "symbols": sum(len(entry.get("symbols") or []) for entry in files_index.values()),
        "dirs": sorted(_dir_counts(files_index)),
        "tables": tables,
        "files_index": files_index,
        "skipped": skipped,
        "exclude": exclude,
    }

    write_json(target, data)
    skeleton_cfg = ctx.config.get("skeleton") or {}
    markdown, symbols_per_file = _fit(
        files_index,
        tables,
        repo,
        generated_at,
        profile.label,
        max_symbols=max(as_int(skeleton_cfg.get("max_symbols"), 12), 1),
    )
    skeleton_md = os.path.join(skeleton_dir(ctx), "SKELETON.md")
    write_text(skeleton_md, markdown)

    recent = recent_commits(repo, as_int(skeleton_cfg.get("recent_days"), 180))
    split_map = as_bool(
        params.get("split_map"), as_bool(skeleton_cfg.get("map_split"), False)
    )
    part_budget = max(
        as_int(
            params.get("map_part_chars"),
            as_int(skeleton_cfg.get("map_part_chars"), MAP_PART_BUDGET),
        ),
        2_000,
    )

    map_md = os.path.join(skeleton_dir(ctx), "MAP.md")
    part_paths: list[str] = []
    if split_map:
        full_map = _render_map(files_index, tables, generated_at, recent, top=None)
        if len(full_map) <= part_budget:
            _clear_map_parts(ctx)
            map_text = full_map
        else:
            scores = rank_files(files_index, recent)
            sections = _map_sections(files_index, scores, None)
            map_text, part_paths = _write_map_parts(
                ctx, sections, generated_at, files_index, tables, part_budget
            )
    else:
        _clear_map_parts(ctx)
        map_text = _fit_text(
            _render_map(files_index, tables, generated_at, recent),
            MAP_BUDGET,
            "Use `code:skeleton level=dir path=<diretório>` para um diretório específico.",
        )
    write_text(map_md, map_text)
    slices = _write_slices(ctx, files_index)

    summary = (
        f"{len(files_index)} arquivo(s), {data['symbols']} símbolo(s), "
        f"{len(tables)} tabela(s) em {elapsed:.1f}s"
    )
    if reused:
        summary += f" ({reused} reaproveitado(s))"

    map_details = f"MAP.md: {map_md} ({len(map_text)} bytes) | dirs/: {slices} fatia(s)"
    if part_paths:
        map_details += f" | mapa completo em {len(part_paths)} parte(s) em map/"
    details = [
        f"project.json: {target} ({os.path.getsize(target)} bytes)",
        f"SKELETON.md: {skeleton_md} ({len(markdown)} bytes, {symbols_per_file} símbolo(s)/arquivo)",
        map_details,
    ]
    if skipped.get("excluded"):
        details.append(f"{skipped['excluded']} arquivo(s) excluído(s) por legacy.exclude/exclude")
    if skipped.get("build_artifacts"):
        details.append(f"{skipped['build_artifacts']} bundle(s) minificado(s) ignorado(s)")
    if skipped.get("large_files"):
        details.append(f"{skipped['large_files']} arquivo(s) grande(s) ignorado(s)")

    artifacts = [target, skeleton_md, map_md, *part_paths]

    if level == "map":
        hint = "Use level=dir path=<diretório> para os símbolos."
        if part_paths:
            hint = "Mapa completo em partes: use `level=part part=<N>` ou `level=dir`."
        return TaskResult(True, summary + " — mapa", details=map_text, artifacts=artifacts,
                          hint=hint)

    if level == "dir":
        grouped = _by_dir(files_index)
        wanted = [
            name
            for name in sorted(grouped)
            if name == dir_path or name.startswith(dir_path + "/") or dir_path == "."
        ]
        if not wanted:
            return TaskResult(
                False,
                f"diretório sem arquivos indexados: {dir_path}",
                hint="Confira `code:skeleton level=map` para os diretórios existentes.",
                exit_code=2,
            )
        text = "\n".join(_render_slice(name, grouped[name]) for name in wanted)
        return TaskResult(
            True,
            f"{len(wanted)} diretório(s) sob {dir_path}/",
            details=text,
            artifacts=artifacts,
            hint="Use um `path` mais específico para reduzir a saída.",
        )

    return TaskResult(
        True,
        summary,
        details="\n".join(details),
        artifacts=artifacts,
    )


register(
    TaskSpec(
        name="code:skeleton",
        intent="read",
        description="Gera o esqueleto do código (símbolos, tabelas, imports) sem copiar fontes",
        required=[],
        optional=["full", "level", "path", "exclude", "split_map", "map_part_chars", "part"],
        handler=handle,
    )
)
