"""watch:clip e watch:downloads (T22/T23) com relógio e desktop simulados."""

import os
import time

from commands.complements.harness import watch
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import watch as watch_task

BLOCK = "```crivonansky\nharness: 1\ntask: prompt\nparams: {}\n```"
RESULT = "```crivonansky-result\nharness: 1\nid: c-1\nstatus: success\n```"


def test_clip_watcher_ignores_initial_content_results_and_repeats():
    clip = {"v": BLOCK}
    handled = []

    def handle(text):
        handled.append(text)
        clip["v"] = RESULT  # o engine copia o resultado de volta
        return [{"status": "success"}]

    watcher = watch.ClipWatcher(lambda: clip["v"], handle)
    assert watcher.poll() is None            # conteúdo inicial não dispara

    clip["v"] = BLOCK + " "
    assert watcher.poll() == [{"status": "success"}]
    assert watcher.poll() is None            # resultado próprio: ignorado
    clip["v"] = "texto qualquer"
    assert watcher.poll() is None            # sem bloco
    clip["v"] = BLOCK + " "
    assert watcher.poll() is not None        # bloco igual ao anterior, mas há texto no meio
    assert len(handled) == 2


def test_classify_files():
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    assert watch.classify("a.patch", diff, "br") == ("patch:apply", {"diff": diff, "branch": "br"})
    assert watch.classify("a.patch", "sem hunk") is None
    state_text = "```crivonansky-state\ntarefa: t\ndecisoes: []\narquivos: []\npendencias: []\nproximo_passo: p\n```"
    assert watch.classify("estado.md", state_text)[0] == "state:save"
    assert watch.classify("foto.png", "x") is None
    assert watch.classify("nota.md", "qualquer coisa") is None


def test_downloads_watcher_processes_once_and_never_deletes(tmp_path):
    folder = tmp_path / "dl"
    folder.mkdir()
    patch = folder / "a.patch"
    patch.write_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8")
    (folder / "lixo.txt").write_text("nada", encoding="utf-8")
    seen = str(tmp_path / "seen.json")
    calls = []

    watcher = watch.DownloadsWatcher(str(folder), lambda b: calls.append(b) or "success",
                                     seen_path=seen, include_existing=True)
    first = watcher.poll()
    second = watcher.poll()

    assert [(n, t, s) for n, t, s in first] == [("a.patch", "patch:apply", "success")]
    assert second == []
    assert patch.exists()
    # após reiniciar, não pergunta de novo
    again = watch.DownloadsWatcher(str(folder), lambda b: calls.append(b) or "success",
                                   seen_path=seen, include_existing=True)
    assert again.poll() == []
    assert len(calls) == 1 and "task: patch:apply" in calls[0]


def test_downloads_watcher_skips_files_older_than_start(tmp_path):
    folder = tmp_path / "dl"
    folder.mkdir()
    old = folder / "velho.patch"
    old.write_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8")
    os.utime(old, (time.time() - 3600, time.time() - 3600))

    watcher = watch.DownloadsWatcher(str(folder), lambda b: "success")

    assert watcher.poll() == []


def _ctx(tmp_path, **prepared):
    return TaskContext(config={}, workspace=str(tmp_path / "ws"), run_dir=str(tmp_path / "run"),
                       prepared=prepared)


class _Engine:
    def __init__(self):
        self.texts = []

    def handle_text(self, text, yes_allowed=False, origin=None):
        self.texts.append((text, origin))
        return [{"status": "success"}], None


def test_watch_clip_task_runs_blocks_as_llm_origin_until_max_cycles(tmp_path):
    clip = {"v": ""}
    engine = _Engine()
    ticks = []

    def sleep(_):
        ticks.append(1)
        clip["v"] = BLOCK

    ctx = _ctx(tmp_path, engine=engine, read_clip=lambda: clip["v"], sleep=sleep)

    result = watch_task.handle_clip(ctx, {"max_cycles": 3})

    assert result.success and "3 ciclo(s)" in result.summary
    assert engine.texts == [(BLOCK, "llm")]


def test_watch_stop_flag_ends_loop(tmp_path):
    ctx = _ctx(tmp_path, engine=_Engine(), read_clip=lambda: "", sleep=lambda _: None)
    assert watch_task.handle_clip(ctx, {"stop": True}).summary == "parada solicitada"

    # a parada pedida antes de iniciar é limpa; um novo pedido durante o loop encerra
    def sleep(_):
        watch.request_stop(str(tmp_path / "ws"))

    ctx = _ctx(tmp_path, engine=_Engine(), read_clip=lambda: "", sleep=sleep)
    assert "parado por --stop" in watch_task.handle_clip(ctx, {}).summary


def test_llm_cannot_start_watchers():
    from commands.complements.harness.policy import llm_task_denied

    assert llm_task_denied({}, "watch:clip")
    assert llm_task_denied({}, "watch:downloads")
