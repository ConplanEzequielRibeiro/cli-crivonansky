"""Tarefa kb:export — pasta pronta para subir no Project do claude.ai (T24)."""

import hashlib
import json
import os
from datetime import datetime

from .. import notes, redact
from ..catalog import register
from ..task_types import TaskResult, TaskSpec
from ..util import as_int, ensure_dir, notes_path, read_text, workspace

DEFAULT_MAX_CHARS = 200_000
MANIFEST_JSON = ".manifest.json"


def _candidates(ctx) -> list[tuple[str, str]]:
    """``[(destino, texto)]`` na ordem de prioridade do corte."""
    items: list[tuple[str, str]] = []
    folder = notes_path(ctx)

    map_path = os.path.join(workspace(ctx), "knowledge", "skeleton", "MAP.md")
    if not os.path.isfile(map_path):
        map_path = os.path.join(folder, "MAPA.md")
    if os.path.isfile(map_path):
        items.append(("MAPA.md", read_text(map_path)))

    glossary = os.path.join(folder, "glossario.md")
    if os.path.isfile(glossary):
        items.append(("glossario.md", read_text(glossary)))

    adr_dir = os.path.join(folder, "adr")
    if os.path.isdir(adr_dir):
        for name in sorted(os.listdir(adr_dir)):
            if name.lower().endswith(".md"):
                items.append((f"adr/{name}", read_text(os.path.join(adr_dir, name))))

    reviewed = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".md") or name.startswith("_") or name in (
                "MAPA.md", "glossario.md"
            ):
                continue
            text = read_text(os.path.join(folder, name))
            try:
                meta, _ = notes.split_note(text)
            except notes.NoteError:
                continue
            if meta.get("revisado") is True:
                reviewed.append((str(meta.get("atualizado_em") or ""), name, text))
    # mais recentes primeiro (não há contagem de consultas registrada)
    for _date, name, text in sorted(reviewed, key=lambda r: (r[0], r[1]), reverse=True):
        items.append((f"fichas/{name}", text))
    return items


def _load_previous(out: str) -> dict:
    try:
        with open(os.path.join(out, MANIFEST_JSON), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def handle(ctx, params):
    cfg = ctx.config.get("kb") or {}
    out = os.path.abspath(
        str(params.get("out") or cfg.get("export_path") or os.path.join(workspace(ctx), "kb_export"))
    )
    limit = as_int(params.get("max_chars"), as_int(cfg.get("max_chars"), DEFAULT_MAX_CHARS))

    items = _candidates(ctx)
    if not items:
        return TaskResult(
            False,
            "nada para exportar",
            hint="Rode `code:skeleton` e salve fichas revisadas com `notes:save`.",
            exit_code=2,
        )

    policy = redact.get_policy(ctx.config)
    previous = _load_previous(out).get("files") or {}
    kept: dict[str, dict] = {}
    omitted: list[str] = []
    stats: dict = {}
    total = 0
    texts: dict[str, str] = {}

    for dest, text in items:
        text, _ = redact.redact_text(text, policy, stats)
        text = text.replace("\r\n", "\n")
        if total + len(text) > limit:
            omitted.append(dest)
            continue
        total += len(text)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        before = previous.get(dest, {}).get("sha256")
        kept[dest] = {
            "sha256": digest,
            "chars": len(text),
            "status": "novo" if before is None else ("igual" if before == digest else "alterado"),
        }
        texts[dest] = text

    removed = sorted(set(previous) - set(kept))
    ensure_dir(out)
    for dest, text in texts.items():
        path = os.path.join(out, dest)
        ensure_dir(os.path.dirname(path))
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    for dest in removed:  # só arquivos que esta exportação gerou antes
        try:
            os.remove(os.path.join(out, dest))
        except OSError:
            pass

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# MANIFEST",
        "",
        f"- exportado em: {now}",
        f"- arquivos: {len(kept)} | caracteres: {total} / {limit}",
        f"- redação: {redact.format_stats(stats) or 'nada mascarado'}",
        "",
        "| arquivo | situação | caracteres | sha256 |",
        "|---|---|---|---|",
    ]
    for dest, info in sorted(kept.items()):
        lines.append(f"| {dest} | {info['status']} | {info['chars']} | {info['sha256'][:12]} |")
    if removed:
        lines += ["", "Removidos desde a última exportação: " + ", ".join(removed)]
    if omitted:
        lines += ["", f"Omitidos pelo limite de tamanho ({len(omitted)}): " + ", ".join(omitted)]
    manifest = "\n".join(lines) + "\n"
    with open(os.path.join(out, "MANIFEST.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(manifest)
    with open(os.path.join(out, MANIFEST_JSON), "w", encoding="utf-8") as fh:
        json.dump({"exported_at": now, "files": kept}, fh, ensure_ascii=False, indent=1)

    changed = sum(1 for i in kept.values() if i["status"] != "igual")
    summary = f"{len(kept)} arquivo(s) exportado(s) ({changed} novo(s)/alterado(s))"
    if omitted:
        summary += f", {len(omitted)} omitido(s) pelo limite"
    return TaskResult(
        True,
        summary,
        details=f"pasta: {out}\n\n{manifest}",
        artifacts=[out],
        hint="Aumente `max_chars` (ou kb.max_chars) para incluir os omitidos." if omitted else "",
    )


register(TaskSpec(
    name="kb:export", intent="write",
    description="Exporta MAPA, glossário, ADRs e fichas revisadas (com redact e MANIFEST) para subir no Project",
    required=[], optional=["out", "max_chars"], handler=handle,
))
