"""Tarefas JIT: busca determinística no código (sem RAG, sem índice vetorial).

Primitivas expostas ao LLM:

* ``code:search``  — ripgrep no repositório (ou nas notas auditadas);
* ``code:read``    — leitura fatiada por intervalo de linhas;
* ``code:outline`` — imports + assinaturas de um arquivo;
* ``code:symbol``  — definições (esqueleto/ast-grep) e referências (ripgrep).

Todas são somente leitura, respeitam ``policy.allowed_roots`` e truncam a saída
com uma dica explícita de refino.
"""

import json
import os
import re
import shutil

from .. import astsym, redact
from ..catalog import register
from ..config import get_tool_path
from ..filters import SKIP_DIRS
from ..formatter import truncation_marker
from ..profiles import resolve_profile
from ..runner import run_process
from ..task_types import TaskResult, TaskSpec
from ..util import (
    as_int,
    ensure_allowed,
    legacy_repo,
    looks_like_path,
    notes_path,
    read_text,
    source_encoding,
    workspace,
)

DEFAULT_MAX_RESULTS = 20
DEFAULT_MAX_LINES = 200
MAX_COLUMN_CHARS = 400

# Labels aceitos pelo ripgrep (encoding_rs) para os encodings comuns do legado.
_RG_ENCODINGS = {
    "cp1252": "windows-1252",
    "latin-1": "windows-1252",
    "iso-8859-1": "windows-1252",
}


def _rg_encoding(encoding: str | None) -> str | None:
    """Label para ``rg --encoding``; ``None`` mantém o padrão (UTF-8)."""
    if not encoding:
        return None
    key = encoding.strip().lower().replace("_", "-")
    if key in ("utf-8", "utf8", "auto"):
        return None
    return _RG_ENCODINGS.get(key, encoding)


# ---------------------------------------------------------------------------
# ripgrep
# ---------------------------------------------------------------------------
def rg_bin(ctx) -> str | None:
    """Caminho do ripgrep: ``tools.rg`` no YAML ou o ``rg`` do PATH."""
    configured = get_tool_path(ctx.config, "rg")
    if configured:
        if looks_like_path(configured):
            return configured if os.path.isfile(configured) else None
        return shutil.which(configured)
    return shutil.which("rg")


def _unavailable(ctx) -> TaskResult:
    return TaskResult(
        False,
        "ripgrep (rg) não encontrado",
        details=(
            "Instale o ripgrep e garanta o `rg` no PATH, ou aponte "
            "`tools.rg` no harness.yaml para o executável.\n"
            "Windows: `winget install BurntSushi.ripgrep.MSVC` ou `choco install ripgrep`."
        ),
        exit_code=2,
        status="unavailable",
    )


def _excludes() -> list[str]:
    args: list[str] = []
    for name in sorted(SKIP_DIRS):
        args.extend(["--glob", f"!**/{name}/**"])
    return args


def _run_rg(
    ctx,
    pattern: str,
    roots: list[str],
    glob: str | None = None,
    encoding: str | None = None,
) -> object:
    binary = rg_bin(ctx)
    cmd = [
        binary,
        "--json",
        "--no-ignore",
        "--max-columns",
        str(MAX_COLUMN_CHARS),
        "--max-columns-preview",
        "--max-filesize",
        "5M",
        *(_excludes()),
    ]
    rg_encoding = _rg_encoding(encoding)
    if rg_encoding:
        cmd.extend(["--encoding", rg_encoding])
    if glob:
        cmd.extend(["--glob", glob])
    cmd.extend([pattern, *roots])

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return run_process(cmd, timeout=120, env=env)


def _matches(stdout: str) -> tuple[list[dict], int, set[str]]:
    """Extrai as ocorrências do ``rg --json`` (total, arquivos distintos)."""
    hits: list[dict] = []
    files: set[str] = set()
    total = 0

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue  # linha de diagnóstico do rg no meio do JSON
        if event.get("type") != "match":
            continue

        data = event.get("data") or {}
        path = (data.get("path") or {}).get("text") or ""
        if not path:
            continue
        text = ((data.get("lines") or {}).get("text") or "").rstrip("\r\n")
        total += 1
        files.add(path)
        hits.append(
            {
                "path": path,
                "line": data.get("line_number") or 0,
                "text": text,
            }
        )

    return hits, total, files


def _display_path(path: str, roots: list[str]) -> str:
    for root in roots:
        try:
            base = os.path.abspath(root)
            full = os.path.abspath(path)
            if os.path.commonpath([full, base]) == base:
                return os.path.relpath(full, base).replace("\\", "/")
        except ValueError:
            continue
    return path.replace("\\", "/")


def _search_root(ctx, scope: str) -> list[str]:
    roots: list[str] = []
    if scope in ("notes", "all"):
        notes = notes_path(ctx)
        if os.path.isdir(notes):
            roots.append(notes)
    if scope in ("repo", "all"):
        roots.append(legacy_repo(ctx))
    return roots


# ---------------------------------------------------------------------------
# code:search
# ---------------------------------------------------------------------------
def handle_search(ctx, params):
    pattern = params.get("pattern")
    if not pattern:
        return TaskResult(False, "parâmetro 'pattern' obrigatório", exit_code=2)

    if rg_bin(ctx) is None:
        return _unavailable(ctx)

    scope = str(params.get("scope") or "repo").lower()
    if scope not in ("repo", "notes", "all"):
        return TaskResult(False, "scope inválido (use repo, notes ou all)", exit_code=2)

    roots = _search_root(ctx, scope)
    if not roots:
        return TaskResult(
            False,
            f"nada para buscar (escopo {scope}): repositório ou notas inexistentes",
            exit_code=2,
        )

    path = params.get("path")
    if path:
        base = roots[0] if scope == "notes" else legacy_repo(ctx)
        try:
            resolved = ensure_allowed(ctx, os.path.join(base, str(path)))
        except PermissionError as exc:
            return TaskResult(False, f"caminho negado: {exc}", exit_code=3, status="denied")
        if not os.path.exists(resolved):
            return TaskResult(False, f"caminho não encontrado: {path}", exit_code=2)
        roots = [resolved]

    try:
        result = _run_rg(
            ctx,
            str(pattern),
            roots,
            params.get("glob"),
            source_encoding(ctx),
        )
    except OSError as exc:
        return TaskResult(False, f"falha ao executar rg: {exc}", exit_code=2)

    if getattr(result, "timed_out", False):
        return TaskResult(
            False, "busca: timeout", details=result.combined, exit_code=124, status="timeout"
        )
    if result.exit_code not in (0, 1):
        return TaskResult(
            False,
            f"rg falhou (exit {result.exit_code})",
            details=result.combined[-2000:],
            exit_code=result.exit_code,
        )

    hits, total, files = _matches(result.stdout)
    if not total:
        return TaskResult(
            True,
            f"nenhuma ocorrência de {pattern!r} (escopo {scope})",
            details="Dica: simplifique o pattern, remova âncoras ou tente `scope: all`.",
        )

    limit = as_int(params.get("max_results"), DEFAULT_MAX_RESULTS)
    limit = max(1, min(limit, 200))
    shown = hits[:limit]

    lines = [
        f"# Busca: {pattern}",
        f"# {total} ocorrência(s) em {len(files)} arquivo(s)"
        + (f" — mostrando {len(shown)}" if total > len(shown) else ""),
        "",
    ]
    for hit in shown:
        text = redact.redact_source(hit["text"][:MAX_COLUMN_CHARS], ctx.config)
        lines.append(f"{_display_path(hit['path'], roots)}:{hit['line']}: {text}")
    if total > len(shown):
        lines.extend(
            [
                "",
                truncation_marker(
                    total - len(shown),
                    "Refine o pattern ou use `path`, `glob` ou `max_results`.",
                    unit="ocorrência(s)",
                ),
            ]
        )

    return TaskResult(
        True,
        f"{total} ocorrência(s) em {len(files)} arquivo(s)"
        + (f" (mostrando {len(shown)})" if total > len(shown) else ""),
        details="\n".join(lines),
        hint="Refine o pattern ou use `path`, `glob` ou `max_results`.",
    )


# ---------------------------------------------------------------------------
# code:read
# ---------------------------------------------------------------------------
def handle_read(ctx, params):
    relative = params.get("file")
    if not relative:
        return TaskResult(False, "parâmetro 'file' obrigatório", exit_code=2)

    try:
        path = ensure_allowed(ctx, str(relative))
    except PermissionError as exc:
        return TaskResult(False, f"caminho negado: {exc}", exit_code=3, status="denied")

    if not os.path.isfile(path):
        return TaskResult(False, f"arquivo não encontrado: {relative}", exit_code=2)

    try:
        text = read_text(path, source_encoding(ctx))
    except OSError as exc:
        return TaskResult(False, f"falha ao ler {relative}: {exc}", exit_code=2)

    text = redact.redact_source(text, ctx.config)
    lines = text.splitlines()
    total = len(lines)
    start = max(1, as_int(params.get("start"), 1))
    max_lines = max(1, min(as_int(params.get("max_lines"), DEFAULT_MAX_LINES), 2000))
    requested_end = as_int(params.get("end"), 0) or (start + max_lines - 1)
    end = min(requested_end, start + max_lines - 1, total)

    if start > total:
        return TaskResult(
            True,
            f"{relative}: início {start} além do fim ({total} linhas)",
            details=f"O arquivo tem {total} linha(s).",
        )

    width = len(str(end))
    body = [f"{number:>{width}}  {lines[number - 1]}" for number in range(start, end + 1)]
    header = f"# {relative}:{start}-{end} (total {total} linhas)"
    details = "\n".join([header, *body])

    truncated = end < total and requested_end > end
    if truncated:
        details += "\n\n" + truncation_marker(
            total - end,
            f"Peça `start={end + 1}` (e `end`) para continuar.",
        )

    return TaskResult(
        True,
        f"{relative}:{start}-{end} de {total} linha(s)",
        details=details,
        artifacts=[path],
        hint="Peça `start`/`end` para ler o trecho seguinte.",
    )


# ---------------------------------------------------------------------------
# code:outline
# ---------------------------------------------------------------------------
def handle_outline(ctx, params):
    relative = params.get("file")
    if not relative:
        return TaskResult(False, "parâmetro 'file' obrigatório", exit_code=2)

    try:
        path = ensure_allowed(ctx, str(relative))
    except PermissionError as exc:
        return TaskResult(False, f"caminho negado: {exc}", exit_code=3, status="denied")

    if not os.path.isfile(path):
        return TaskResult(False, f"arquivo não encontrado: {relative}", exit_code=2)

    try:
        profile = resolve_profile(ctx.config)
    except ValueError as exc:
        return TaskResult(False, str(exc), exit_code=2)

    text = read_text(path, profile.encoding)
    symbols = astsym.definitions(
        text, path, profile.languages, profile.definition_kinds
    )
    imports = astsym.extract_imports(text, path, profile.import_patterns)

    parts = [f"# outline: {relative} ({len(text.splitlines())} linhas)", ""]
    if imports:
        parts.extend(["## imports", *[f"- {item}" for item in imports], ""])
    parts.append("## símbolos")
    if symbols:
        for symbol in symbols:
            parts.append(f"- L{symbol['line']}-{symbol['end']} {symbol['kind']} {symbol['name']}")
    else:
        parts.append("- (nenhuma definição reconhecida)")
    parts.extend(["", "Dica: `code:read file=<arquivo> start=<linha>` para ver o corpo."])

    return TaskResult(
        True,
        f"{relative}: {len(symbols)} símbolo(s), {len(imports)} import(s)",
        details="\n".join(parts),
    )


# ---------------------------------------------------------------------------
# code:symbol
# ---------------------------------------------------------------------------
def _skeleton_path(ctx) -> str:
    return os.path.join(workspace(ctx), "knowledge", "skeleton", "project.json")


def _definitions_from_skeleton(ctx, name: str) -> list[dict] | None:
    path = _skeleton_path(ctx)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None

    found: list[dict] = []
    for relative, entry in (data.get("files_index") or {}).items():
        for symbol in entry.get("symbols") or []:
            if symbol.get("name") == name:
                found.append(
                    {
                        "file": relative,
                        "line": symbol.get("line"),
                        "end": symbol.get("end"),
                        "kind": symbol.get("kind", "function"),
                    }
                )
    found.sort(key=lambda item: (item["file"], item["line"] or 0))
    return found if found else []


def _candidate_files(ctx, name: str, profile) -> list[str]:
    """Arquivos que contêm o nome (pré-filtro barato antes de parsear)."""
    binary = rg_bin(ctx)
    root = legacy_repo(ctx)
    if binary:
        cmd = [
            binary,
            "--files-with-matches",
            "--no-ignore",
            "--fixed-strings",
            "--max-filesize",
            "5M",
            *(_excludes()),
        ]
        rg_encoding = _rg_encoding(profile.encoding)
        if rg_encoding:
            cmd.extend(["--encoding", rg_encoding])
        cmd.extend([name, root])
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            result = run_process(cmd, timeout=60, env=env)
        except OSError:
            result = None
        if result is not None and result.exit_code in (0, 1):
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    from ..filters import iter_files

    return [
        path
        for path in iter_files(root)
        if name in read_text(path, profile.encoding)
    ]


def _scan_definitions(ctx, name: str, profile) -> list[dict]:
    root = legacy_repo(ctx)
    found: list[dict] = []
    for path in _candidate_files(ctx, name, profile):
        text = read_text(path, profile.encoding)
        if name not in text:
            continue
        relative = os.path.relpath(path, root).replace("\\", "/")
        for symbol in astsym.definitions(
            text, path, profile.languages, profile.definition_kinds
        ):
            if symbol["name"] == name:
                found.append({"file": relative, **symbol})
    found.sort(key=lambda item: (item["file"], item["line"]))
    return found


def _reference_hits(
    ctx, name: str, max_results: int, profile
) -> tuple[list[dict], int]:
    if rg_bin(ctx) is None:
        return [], 0
    pattern = rf"\b{re.escape(name)}\s*\("
    result = _run_rg(ctx, pattern, [legacy_repo(ctx)], encoding=profile.encoding)
    if getattr(result, "timed_out", False):
        return [], 0
    hits, total, _files = _matches(result.stdout)
    return hits[:max_results], total


def handle_symbol(ctx, params):
    name = params.get("name")
    if not name:
        return TaskResult(False, "parâmetro 'name' obrigatório", exit_code=2)
    name = str(name)

    kind = str(params.get("kind") or "def").lower()
    if kind not in ("def", "ref", "both"):
        return TaskResult(False, "kind inválido (use def, ref ou both)", exit_code=2)
    if kind in ("ref", "both") and rg_bin(ctx) is None:
        return _unavailable(ctx)

    try:
        profile = resolve_profile(ctx.config)
    except ValueError as exc:
        return TaskResult(False, str(exc), exit_code=2)

    limit = max(1, min(as_int(params.get("max_results"), 30), 200))

    definitions: list[dict] = []
    if kind in ("def", "both"):
        definitions = _definitions_from_skeleton(ctx, name)
        if definitions is None:
            definitions = _scan_definitions(ctx, name, profile)
        definitions = definitions[:limit]

    references: list[dict] = []
    total_refs = 0
    if kind in ("ref", "both"):
        references, total_refs = _reference_hits(ctx, name, limit, profile)
        definition_lines = {
            (item["file"], item["line"]) for item in definitions if item.get("line")
        }
        root = legacy_repo(ctx)
        filtered = []
        for hit in references:
            relative = os.path.relpath(hit["path"], root).replace("\\", "/")
            if (relative, hit["line"]) in definition_lines:
                continue
            filtered.append(
                {
                    **hit,
                    "file": relative,
                    "text": redact.redact_source(hit["text"], ctx.config),
                }
            )
        total_refs = max(0, total_refs - (len(references) - len(filtered)))
        references = filtered

    parts = [f"# símbolo: {name}", ""]
    if kind in ("def", "both"):
        parts.append("## definições")
        if definitions:
            for item in definitions:
                parts.append(
                    f"- {item['file']}:{item['line']}-{item.get('end', item['line'])} "
                    f"({item.get('kind', 'function')})"
                )
        else:
            parts.append("- (nenhuma; rode `code:skeleton` para atualizar o índice)")
        parts.append("")

    if kind in ("ref", "both"):
        parts.append("## referências (chamadas)")
        if references:
            for hit in references:
                parts.append(f"- {hit['file']}:{hit['line']}: {hit['text'][:200]}")
        else:
            parts.append("- (nenhuma chamada encontrada)")
        if total_refs > len(references):
            parts.extend(
                [
                    "",
                    truncation_marker(
                        total_refs - len(references),
                        "Refine com `max_results` ou use `code:search` com `path`.",
                        unit="referência(s)",
                    ),
                ]
            )

    summary = f"{len(definitions)} definição(ões)"
    if kind in ("ref", "both"):
        summary += f", {total_refs} referência(s)"

    return TaskResult(True, summary, details="\n".join(parts))


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
register(
    TaskSpec(
        name="code:search",
        intent="read",
        description="Busca textual (ripgrep) no repositório ou nas notas",
        required=["pattern"],
        optional=["path", "glob", "max_results", "scope"],
        handler=handle_search,
    )
)

register(
    TaskSpec(
        name="code:read",
        intent="read",
        description="Lê um intervalo de linhas de um arquivo",
        required=["file"],
        optional=["start", "end", "max_lines"],
        handler=handle_read,
    )
)

register(
    TaskSpec(
        name="code:outline",
        intent="read",
        description="Lista imports e assinaturas de um arquivo",
        required=["file"],
        optional=[],
        handler=handle_outline,
    )
)

register(
    TaskSpec(
        name="code:symbol",
        intent="read",
        description="Localiza definições e chamadas de um símbolo",
        required=["name"],
        optional=["kind", "max_results"],
        handler=handle_symbol,
    )
)
