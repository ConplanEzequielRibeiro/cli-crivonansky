"""Tarefas de fichas: notes:draft, notes:save e notes:stale (T13–T16)."""

import difflib
import json
import os

from .. import notes
from ..catalog import register
from ..task_types import TaskResult, TaskSpec
from ..util import (
    as_bool,
    as_list,
    ensure_allowed,
    ensure_dir,
    is_within,
    legacy_repo,
    notes_path,
    read_text,
)
from . import skeleton

DRAFT_INSTRUCTION = (
    "Complete as seções acima com base no código que você leu (use `code:outline`, "
    "`code:symbol` e `code:read` com intervalo). Mantenha o frontmatter e as seis "
    "seções; não invente: marque o que não souber como `A confirmar`. "
    "Devolva a ficha inteira num único bloco de código Markdown."
)


def _load_index(ctx) -> dict | None:
    try:
        with open(skeleton.project_path(ctx), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _note_files(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if name.lower().endswith(".md") and not name.startswith("_")
    )


# ---------------------------------------------------------------------------
# notes:draft
# ---------------------------------------------------------------------------
def handle_draft(ctx, params):
    module = str(params.get("module") or "").replace("\\", "/").strip("/")
    if not module:
        return TaskResult(False, "parâmetro 'module' obrigatório (diretório do módulo)", exit_code=2)

    index = _load_index(ctx)
    if index is None:
        return TaskResult(
            False,
            "esqueleto ainda não gerado",
            hint="Rode `code:skeleton` antes de `notes:draft`.",
            exit_code=2,
        )

    files_index = index.get("files_index") or {}
    selected = {
        path: entry
        for path, entry in files_index.items()
        if os.path.dirname(path) == module or os.path.dirname(path).startswith(module + "/")
    }
    if not selected:
        return TaskResult(
            False,
            f"nenhum arquivo indexado em {module}/",
            hint="Confira os diretórios em `code:skeleton level=map`.",
            exit_code=2,
        )

    scores = skeleton.rank_files(files_index)
    limit = 15
    ranked = sorted(selected, key=lambda path: (-scores.get(path, 0), path))
    chosen = sorted(ranked[:limit])
    tables = sorted({t for path in chosen for t in selected[path].get("tables") or []})

    target = os.path.join(notes_path(ctx), notes.note_filename(module))
    existing_meta: dict = {}
    existing_body = ""
    if os.path.isfile(target):
        try:
            existing_meta, existing_body = notes.split_note(read_text(target))
        except notes.NoteError:
            existing_meta, existing_body = {}, ""

    meta = {
        "modulo": existing_meta.get("modulo") or module,
        "tags": list(existing_meta.get("tags") or [os.path.basename(module)]),
        "tabelas": sorted(set(existing_meta.get("tabelas") or []) | set(tables)),
        "arquivos": sorted(set(existing_meta.get("arquivos") or []) | set(chosen)),
        "revisado": False,
    }
    meta = notes.stamp(meta, legacy_repo(ctx))

    symbols_view = []
    for path in chosen:
        entry = selected[path]
        names = ", ".join(
            f"{s['name']}(L{s['line']})" for s in (entry.get("symbols") or [])[:8]
        )
        symbols_view.append(f"- `{path}` ({entry.get('loc', 0)} LOC): {names}")

    body = existing_body.strip("\n")
    if not body:
        body = "# " + module + "\n\n" + notes.skeleton_body()

    omitted = len(selected) - len(chosen)
    context = [
        "## Material levantado (apague antes de salvar)",
        "",
        *symbols_view,
    ]
    if omitted > 0:
        context.append(
            f"- [truncado: {omitted} arquivo(s) omitido(s) — menor relevância. "
            f"Use `code:skeleton level=dir path={module}`.]"
        )
    if tables:
        context += ["", "Tabelas: " + ", ".join(f"`{t}`" for t in tables)]

    text = (
        notes.render_note(meta, body)
        + "\n"
        + "\n".join(context)
        + "\n\n---\n"
        + DRAFT_INSTRUCTION
        + "\n"
    )
    return TaskResult(
        True,
        f"rascunho da ficha {module} ({len(chosen)} arquivo(s), {len(tables)} tabela(s))",
        details=text,
        hint="Cole a ficha devolvida em `notes:save`.",
    )


# ---------------------------------------------------------------------------
# notes:save
# ---------------------------------------------------------------------------
def _incoming_text(ctx, params) -> str:
    if params.get("content"):
        return str(params["content"])
    if as_bool(params.get("clip")):
        import pyperclip

        return str(pyperclip.paste() or "")
    if params.get("file"):
        return read_text(ensure_allowed(ctx, str(params["file"])))
    return ""


def _strip_context(body: str) -> str:
    """Remove o bloco 'Material levantado' que o rascunho acrescenta."""
    marker = "## Material levantado"
    index = body.find(marker)
    return body[:index].rstrip("\n") + "\n" if index >= 0 else body


def _prepare(ctx, params) -> tuple[str, str, str]:
    """Devolve (caminho, texto final, texto atual) ou levanta ``NoteError``."""
    raw = _incoming_text(ctx, params)
    if not raw.strip():
        raise notes.NoteError("nenhuma ficha informada (use content, file ou clip)")

    # Se vier dentro de um bloco ```markdown, extrai.
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])

    meta, body = notes.split_note(text)
    body = _strip_context(body)
    problems = notes.validate_meta(meta, body)
    if problems:
        raise notes.NoteError("; ".join(problems))

    meta = notes.stamp(meta, legacy_repo(ctx))
    folder = notes_path(ctx)
    path = os.path.abspath(os.path.join(folder, notes.note_filename(str(meta["modulo"]))))
    if not is_within(path, [folder]):
        raise notes.NoteError("destino fora de notes_path")

    final = notes.render_note(meta, body)
    current = read_text(path) if os.path.isfile(path) else ""
    return path, final, current


def preview_save(ctx, params):
    try:
        path, final, current = _prepare(ctx, params)
    except notes.NoteError as exc:
        return f"(ficha inválida: {exc})"
    ctx.prepared["note"] = (path, final)
    name = os.path.basename(path)
    if not current:
        return f"Nova ficha: {name}\n{final}"
    diff = list(
        difflib.unified_diff(
            current.replace("\r\n", "\n").splitlines(),
            final.splitlines(),
            fromfile=f"{name} (atual)",
            tofile=f"{name} (nova)",
            lineterm="",
        )
    )
    return "\n".join(diff) if diff else f"{name}: sem mudanças"


def handle_save(ctx, params):
    try:
        path, final = ctx.prepared.get("note") or _prepare(ctx, params)[:2]
    except notes.NoteError as exc:
        return TaskResult(False, f"ficha inválida: {exc}", exit_code=2)

    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(final)
    return TaskResult(
        True,
        f"ficha gravada: {os.path.basename(path)}",
        details=f"caminho: {path}\n(sem commit automático; revise e faça commit no repositório de notas)",
        artifacts=[path],
    )


# ---------------------------------------------------------------------------
# notes:stale
# ---------------------------------------------------------------------------
def handle_stale(ctx, params):
    folder = notes_path(ctx)
    repo = legacy_repo(ctx)
    files = _note_files(folder)
    if not files:
        return TaskResult(True, "nenhuma ficha encontrada", details=f"pasta: {folder}")

    stale, invalid = [], []
    for path in files:
        name = os.path.basename(path)
        try:
            meta, _body = notes.split_note(read_text(path))
        except notes.NoteError as exc:
            invalid.append(f"- {name}: {exc}")
            continue
        listed = [str(item) for item in as_list(meta.get("arquivos"))]
        changed = notes.changed_files(repo, listed, str(meta.get("hash_fonte") or ""))
        if changed:
            stale.append(
                f"- {name}: {', '.join(changed[:5])}"
                + (f" (+{len(changed) - 5})" if len(changed) > 5 else "")
                + f" | revisado: {meta.get('revisado')} | atualizado em: {meta.get('atualizado_em') or '?'}"
            )

    lines = []
    if stale:
        lines += [f"Fichas desatualizadas ({len(stale)}):", *stale]
    if invalid:
        lines += ["", f"Fichas inválidas ({len(invalid)}):", *invalid]
    summary = f"{len(stale)} ficha(s) desatualizada(s) de {len(files)}"
    return TaskResult(
        True,
        summary,
        details="\n".join(lines) if lines else "todas as fichas estão em dia",
        hint="Use `notes:draft module=<dir>` para atualizar uma ficha." if stale else "",
    )


register(
    TaskSpec(
        name="notes:draft",
        intent="read",
        description="Monta o rascunho de uma ficha de módulo (frontmatter + seções) para o chat completar",
        required=["module"],
        optional=[],
        handler=handle_draft,
    )
)
register(
    TaskSpec(
        name="notes:save",
        intent="write",
        description="Valida e grava uma ficha em notes_path (recalcula hash_fonte; mostra diff)",
        required=[],
        optional=["content", "file", "clip"],
        handler=handle_save,
        preview_fn=preview_save,
    )
)
register(
    TaskSpec(
        name="notes:stale",
        intent="read",
        description="Lista as fichas cujos arquivos de origem mudaram desde a última revisão",
        required=[],
        optional=[],
        handler=handle_stale,
    )
)
