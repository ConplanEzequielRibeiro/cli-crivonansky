"""Tarefas watch:clip e watch:downloads (T22/T23): loops de longa duração."""

import os
import time

from .. import watch
from commands.complements.harness_core.catalog import register
from commands.complements.harness_core.task_types import TaskResult, TaskSpec
from commands.complements.harness_core.util import as_bool, as_int, workspace


def _engine(ctx):
    factory = ctx.prepared.get("engine")
    if factory is not None:
        return factory
    from commands.complements.harness_core.engine import HarnessEngine

    return HarnessEngine(config=ctx.config, interactive=True)


def _loop(ctx, params, step):
    """Executa ``step`` a cada intervalo até Ctrl+C, arquivo de parada ou ``max_cycles``."""
    interval = max(as_int(params.get("interval_ms"), 500), 10) / 1000.0
    max_cycles = as_int(params.get("max_cycles"), 0)
    sleep = ctx.prepared.get("sleep") or time.sleep
    ws = workspace(ctx)
    watch.clear_stop(ws)
    cycles = 0
    try:
        while True:
            step()
            cycles += 1
            if watch.stop_requested(ws):
                watch.clear_stop(ws)
                return "parado por --stop"
            if max_cycles and cycles >= max_cycles:
                return f"{cycles} ciclo(s)"
            sleep(interval)
    except KeyboardInterrupt:
        return "interrompido (Ctrl+C)"


def handle_clip(ctx, params):
    ws = workspace(ctx)
    if as_bool(params.get("stop")):
        path = watch.request_stop(ws)
        return TaskResult(True, "parada solicitada", details=path)

    engine = _engine(ctx)
    read = ctx.prepared.get("read_clip")
    if read is None:
        import pyperclip

        read = pyperclip.paste

    def handle(text):
        results, _error = engine.handle_text(text, yes_allowed=False, origin="llm")
        for item in results:
            print(f"[watch:clip] {item['status']}")
        return results

    watcher = watch.ClipWatcher(read, handle)
    reason = _loop(ctx, params, watcher.poll)
    return TaskResult(True, f"watch:clip encerrado: {reason}", details=f"blocos tratados: {watcher.handled}")


def handle_downloads(ctx, params):
    ws = workspace(ctx)
    if as_bool(params.get("stop")):
        path = watch.request_stop(ws)
        return TaskResult(True, "parada solicitada", details=path)

    cfg = (ctx.config.get("watch") or {})
    folder = str(params.get("path") or cfg.get("downloads_path") or watch.default_downloads())
    if not os.path.isdir(folder):
        return TaskResult(False, f"pasta inexistente: {folder}", exit_code=2)

    engine = _engine(ctx)

    def handle(block):
        text, status = engine.handle_block(block, yes_allowed=False, origin="llm")
        return status

    watcher = watch.DownloadsWatcher(
        folder,
        handle,
        seen_path=os.path.join(ws, "runs", watch.SEEN_FILE),
        include_existing=as_bool(params.get("include_existing")),
        patch_branch=params.get("branch") or cfg.get("patch_branch"),
    )
    processed = []

    def step():
        for name, task, status in watcher.poll():
            print(f"[watch:downloads] {name} -> {task}: {status}")
            processed.append((name, task, status))

    reason = _loop(ctx, params, step)
    lines = [f"- {n} -> {t}: {s}" for n, t, s in processed] or ["(nenhum arquivo tratado)"]
    return TaskResult(True, f"watch:downloads encerrado: {reason}", details="\n".join(lines))


register(TaskSpec(
    name="watch:clip", pack="harness_watch", intent="read",
    description="Monitora o clipboard e executa blocos crivonansky novos (com a política e o y/N do exec)",
    required=[], optional=["interval_ms", "stop", "max_cycles"], handler=handle_clip,
))
register(TaskSpec(
    name="watch:downloads", pack="harness_watch", intent="read",
    description="Monitora a pasta de downloads: .patch e estados (sempre com confirmação)",
    required=[], optional=["path", "interval_ms", "stop", "max_cycles", "branch", "include_existing"],
    handler=handle_downloads,
))
