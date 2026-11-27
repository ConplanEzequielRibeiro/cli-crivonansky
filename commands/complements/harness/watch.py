"""Lógica de monitoramento (clipboard e pasta de downloads), sem I/O de loop.

``ClipWatcher`` e ``DownloadsWatcher`` recebem funções injetadas (ler clipboard,
executar texto, listar pasta) para serem testados sem relógio nem desktop.
"""

import hashlib
import json
import os
import re
import time

import yaml

from . import state
from .contract import extract_blocks

STOP_FILE = "watch.stop"
SEEN_FILE = "watch-downloads.json"
PATCH_EXT = (".patch", ".diff")
TEXT_EXT = (".md", ".txt")
MAX_FILE_BYTES = 2_000_000


def _digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def stop_path(workspace: str) -> str:
    return os.path.join(workspace, "runs", STOP_FILE)


def request_stop(workspace: str) -> str:
    path = stop_path(workspace)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%dT%H:%M:%S"))
    return path


def clear_stop(workspace: str) -> None:
    try:
        os.remove(stop_path(workspace))
    except OSError:
        pass


def stop_requested(workspace: str) -> bool:
    return os.path.isfile(stop_path(workspace))


class ClipWatcher:
    """Reage a blocos ``crivonansky`` novos no clipboard (sem repetir nem se auto-disparar)."""

    def __init__(self, read, handle):
        self.read = read      # () -> str
        self.handle = handle  # (text) -> list[dict] (statuses)
        self.last = _digest(read())  # o que já está no clipboard ao iniciar não dispara
        self.handled = 0

    def poll(self) -> list[dict] | None:
        text = self.read() or ""
        digest = _digest(text)
        if digest == self.last:
            return None
        self.last = digest
        if not extract_blocks(text):  # inclui ignorar o próprio crivonansky-result
            return None
        results = self.handle(text)
        self.handled += 1
        # O resultado copiado de volta passa a ser o "último visto".
        self.last = _digest(self.read() or "")
        return results


def classify(path: str, text: str, patch_branch: str | None = None):
    """Decide a tarefa para um arquivo baixado: ``(tarefa, params)`` ou ``None``."""
    lower = path.lower()
    if lower.endswith(PATCH_EXT):
        if "\n@@ " not in "\n" + text:
            return None
        params = {"diff": text}
        if patch_branch:
            params["branch"] = patch_branch
        return "patch:apply", params
    if lower.endswith(TEXT_EXT):
        if state.extract_state(text) is not None:
            try:
                state.parse_state(text)
            except state.StateError:
                return None
            return "state:save", {"content": text}
        # Fichas/notas foram removidas na R0.6; `.md`/`.txt` sem estado é ignorado.
        return None
    return None


def block_yaml(task: str, params: dict) -> str:
    return yaml.safe_dump(
        {"harness": 1, "task": task, "params": params}, allow_unicode=True, sort_keys=False
    )


class DownloadsWatcher:
    def __init__(self, folder, handle, seen_path=None, started=None, include_existing=False,
                 patch_branch=None):
        self.folder = folder
        self.handle = handle  # (yaml_block) -> status
        self.seen_path = seen_path
        self.started = time.time() if started is None else started
        self.include_existing = include_existing
        self.patch_branch = patch_branch
        self.seen = self._load()

    def _load(self) -> set[str]:
        if not self.seen_path:
            return set()
        try:
            with open(self.seen_path, "r", encoding="utf-8") as fh:
                return set(json.load(fh))
        except (OSError, ValueError):
            return set()

    def _save(self) -> None:
        if not self.seen_path:
            return
        os.makedirs(os.path.dirname(self.seen_path), exist_ok=True)
        with open(self.seen_path, "w", encoding="utf-8") as fh:
            json.dump(sorted(self.seen), fh, ensure_ascii=False)

    def poll(self) -> list[tuple[str, str, str]]:
        """Processa arquivos novos. Devolve ``[(arquivo, tarefa, status)]``; nunca apaga."""
        done = []
        try:
            names = sorted(os.listdir(self.folder))
        except OSError:
            return done
        for name in names:
            path = os.path.join(self.folder, name)
            try:
                info = os.stat(path)
            except OSError:
                continue
            if not os.path.isfile(path) or info.st_size > MAX_FILE_BYTES:
                continue
            if not self.include_existing and info.st_mtime < self.started - 2:
                continue
            key = f"{path}|{int(info.st_mtime)}|{info.st_size}"
            if key in self.seen:
                continue
            if name.lower().endswith((".crdownload", ".part", ".tmp")):
                continue
            self.seen.add(key)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            picked = classify(path, text, self.patch_branch)
            if picked is None:
                continue
            task, params = picked
            done.append((name, task, self.handle(block_yaml(task, params))))
        self._save()
        return done


def default_downloads() -> str:
    return os.path.join(os.path.expanduser("~"), "Downloads")
