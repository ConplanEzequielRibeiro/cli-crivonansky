"""Tarefas de limpeza do workspace: ``clean:artifacts`` e ``clean:runs``.

Nunca tocam o repositório legado, o ``harness.yaml`` nem ``knowledge/notes`` legado
(dados legados não são artefatos descartáveis).
"""

import json
import os
import re
import shutil
import time

from ..catalog import register
from ..task_types import TaskResult, TaskSpec
from ..util import as_bool, as_int, as_list, workspace

# Artefatos que podem ser regerados pelas tarefas de coleta.
ARTIFACT_SCOPES = {
    "skeleton": ("knowledge", "skeleton"),
    "db": ("knowledge", "db"),
    "links": ("knowledge", "links"),
    "docs": ("knowledge", "docs"),
    "legacy-code": ("knowledge", "code"),
}

_ALIASES = {
    "legacy": "legacy-code",
    "code": "legacy-code",
    "codigo": "legacy-code",
}

RUN_ID_RE = re.compile(r"^c-[0-9a-f]{8}$")


def _size(path: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total


def _mb(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _scopes(params: dict) -> tuple[list[str], str | None]:
    raw = params.get("scope")
    requested = as_list(raw) if raw else ["all"]
    scopes: list[str] = []
    for item in requested:
        name = str(item).strip().lower()
        name = _ALIASES.get(name, name)
        if name == "all":
            scopes.extend(ARTIFACT_SCOPES)
            continue
        if name not in ARTIFACT_SCOPES:
            available = ", ".join(sorted(ARTIFACT_SCOPES) + ["all"])
            return [], f"scope desconhecido: {item} (use: {available})"
        scopes.append(name)
    # preserva a ordem do dicionário e remove duplicatas
    ordered = [name for name in ARTIFACT_SCOPES if name in set(scopes)]
    return ordered, None


def _artifact_plan(ctx, scopes: list[str]) -> list[dict]:
    base = os.path.join(workspace(ctx), *ARTIFACT_SCOPES["skeleton"][:1])
    plan = []
    for scope in scopes:
        relative = os.path.join(*ARTIFACT_SCOPES[scope])
        path = os.path.join(workspace(ctx), relative)
        # Guarda-corpo: só remove dentro de <workspace>/knowledge/<scope>.
        if os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) != os.path.abspath(base):
            continue
        exists = os.path.isdir(path)
        plan.append(
            {
                "scope": scope,
                "path": path,
                "relative": relative.replace("\\", "/"),
                "exists": exists,
                "size": _size(path) if exists else 0,
            }
        )
    return plan


def _format_artifact_plan(plan: list[dict], removing: bool) -> str:
    lines = []
    for item in plan:
        state = "remover" if (removing and item["exists"]) else (
            "seria removido" if item["exists"] else "ausente"
        )
        lines.append(f"- {item['relative']} ({_mb(item['size'])}) — {state}")
    total = sum(item["size"] for item in plan if item["exists"])
    lines.append("")
    lines.append(f"total: {_mb(total)}")
    return "\n".join(lines)


def preview_artifacts(ctx, params) -> str | None:
    scopes, error = _scopes(params)
    if error:
        return error
    return _format_artifact_plan(_artifact_plan(ctx, scopes), removing=False)


def handle_artifacts(ctx, params):
    scopes, error = _scopes(params)
    if error:
        return TaskResult(False, error, exit_code=2)

    plan = _artifact_plan(ctx, scopes)
    existing = [item for item in plan if item["exists"]]
    total = sum(item["size"] for item in existing)

    if as_bool(params.get("dry_run")):
        return TaskResult(
            True,
            f"{len(existing)} área(s) ({_mb(total)}) seriam removidas",
            details=_format_artifact_plan(plan, removing=False),
        )

    if not existing:
        return TaskResult(True, "nada a limpar", details=_format_artifact_plan(plan, removing=True))

    removed = []
    errors = []
    for item in existing:
        try:
            shutil.rmtree(item["path"])
            removed.append(item)
        except OSError as exc:
            errors.append(f"{item['relative']}: {exc}")

    summary = f"{len(removed)} área(s) removida(s) ({_mb(sum(item['size'] for item in removed))})"
    details = [f"- {item['relative']}" for item in removed]
    details.extend(f"- erro: {message}" for message in errors)
    return TaskResult(
        not errors,
        summary if not errors else summary + f"; {len(errors)} erro(s)",
        details="\n".join(details),
        artifacts=[item["path"] for item in removed],
        exit_code=0 if not errors else 1,
    )


# ---------------------------------------------------------------------------
# clean:runs
# ---------------------------------------------------------------------------
def _run_dirs(ctx) -> list[dict]:
    folder = os.path.join(workspace(ctx), "runs")
    if not os.path.isdir(folder):
        return []

    runs = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isdir(path) or not RUN_ID_RE.match(name):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        runs.append({"id": name, "path": path, "mtime": mtime, "size": _size(path)})
    return runs


def _run_plan(ctx, days: int, keep: int) -> tuple[list[dict], list[dict]]:
    runs = sorted(_run_dirs(ctx), key=lambda item: item["mtime"], reverse=True)
    protected = {item["id"] for item in runs[: max(keep, 0)]}
    cutoff = time.time() - days * 86_400
    candidates = [
        item
        for item in runs
        if item["id"] not in protected and item["mtime"] <= cutoff
    ]
    return candidates, runs


def _format_run_plan(candidates: list[dict], runs: list[dict], removing: bool) -> str:
    lines = [f"- execuções no workspace: {len(runs)}"]
    for item in candidates:
        state = "remover" if removing else "seria removida"
        lines.append(f"- {item['id']} ({_mb(item['size'])}) — {state}")
    lines.append("")
    lines.append(f"total a remover: {_mb(sum(item['size'] for item in candidates))}")
    return "\n".join(lines)


def preview_runs(ctx, params) -> str | None:
    days = max(as_int(params.get("days"), 30), 0)
    keep = max(as_int(params.get("keep"), 100), 0)
    candidates, runs = _run_plan(ctx, days, keep)
    return _format_run_plan(candidates, runs, removing=False)


def _compact_index(ctx, remaining: set[str]) -> tuple[int, int]:
    """Reescreve ``runs.jsonl`` só com execuções cujo diretório ainda existe."""
    path = os.path.join(workspace(ctx), "runs", "runs.jsonl")
    if not os.path.isfile(path):
        return 0, 0

    kept = []
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("id") in remaining:
                kept.append(line)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for line in kept:
            fh.write(line + "\n")
    os.replace(tmp, path)
    return total, len(kept)


def handle_runs(ctx, params):
    days = max(as_int(params.get("days"), 30), 0)
    keep = max(as_int(params.get("keep"), 100), 0)
    candidates, runs = _run_plan(ctx, days, keep)

    if as_bool(params.get("dry_run")):
        return TaskResult(
            True,
            f"{len(candidates)} execução(ões) seriam removidas",
            details=_format_run_plan(candidates, runs, removing=False),
        )

    if not candidates:
        return TaskResult(
            True,
            "nada a limpar",
            details=_format_run_plan(candidates, runs, removing=True),
        )

    removed = []
    errors = []
    for item in candidates:
        try:
            shutil.rmtree(item["path"])
            removed.append(item)
        except OSError as exc:
            errors.append(f"{item['id']}: {exc}")

    remaining = {item["id"] for item in runs if item["id"] not in {r["id"] for r in removed}}
    before, after = _compact_index(ctx, remaining)

    summary = (
        f"{len(removed)} execução(ões) removida(s) "
        f"({_mb(sum(item['size'] for item in removed))}); índice {before} -> {after} linha(s)"
    )
    details = [f"- {item['id']}" for item in removed]
    details.extend(f"- erro: {message}" for message in errors)
    return TaskResult(
        not errors,
        summary if not errors else summary + f"; {len(errors)} erro(s)",
        details="\n".join(details),
        artifacts=[item["path"] for item in removed],
        exit_code=0 if not errors else 1,
    )


def _intent(params) -> str:
    return "read" if as_bool(params.get("dry_run")) else "write"


register(
    TaskSpec(
        name="clean:artifacts", pack="harness_clean",
        intent="write",
        description="Remove artefatos regeráveis do workspace (knowledge/*, exceto notas legadas)",
        required=[],
        optional=["scope", "dry_run"],
        handler=handle_artifacts,
        intent_fn=_intent,
        preview_fn=preview_artifacts,
    )
)

register(
    TaskSpec(
        name="clean:runs", pack="harness_clean",
        intent="write",
        description="Remove execuções antigas de runs/ e compacta o runs.jsonl",
        required=[],
        optional=["days", "keep", "dry_run"],
        handler=handle_runs,
        intent_fn=_intent,
        preview_fn=preview_runs,
    )
)
