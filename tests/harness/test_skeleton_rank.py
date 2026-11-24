"""Ranking por commits recentes, skeleton.max_symbols e --clip do notes:save."""

import subprocess

from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import notes as notes_task
from commands.complements.harness.tasks import skeleton


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _ctx(tmp_path, extra=None):
    config = {"legacy": {"repo_path": str(tmp_path / "repo")}}
    config.update(extra or {})
    return TaskContext(config=config, workspace=str(tmp_path / "ws"), run_dir=str(tmp_path / "run"))


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "mod").mkdir(parents=True)
    for name in ("a", "b", "c"):
        (repo / "mod" / f"{name}.php").write_text("<?php\nfunction f_%s() {}\n" % name, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    for n in range(3):
        (repo / "mod" / "c.php").write_text(
            "<?php\nfunction f_c() {}\n// mudança %d\n" % n, encoding="utf-8"
        )
        _git(repo, "commit", "-qam", f"c{n}")
    return repo


def test_recent_commits_counts_changed_files(tmp_path):
    repo = _repo(tmp_path)

    counts = skeleton.recent_commits(str(repo))

    assert counts["mod/c.php"] == 4
    assert counts["mod/a.php"] == 1
    assert skeleton.recent_commits(str(tmp_path / "sem-git")) == {}
    assert skeleton.recent_commits(str(repo), days=0) == {}


def test_rank_prefers_recently_changed_file():
    index = {f"d/{n}.php": {"loc": 10, "symbols": [], "tables": [], "imports": []} for n in "abc"}

    scores = skeleton.rank_files(index, {"d/c.php": 5})

    assert scores["d/c.php"] > scores["d/a.php"] == scores["d/b.php"]


def test_map_puts_recent_file_first(tmp_path):
    _repo(tmp_path)

    skeleton.handle(_ctx(tmp_path), {})

    mapa = (tmp_path / "ws/knowledge/skeleton/MAP.md").read_text(encoding="utf-8")
    first = mapa.split("## mod/ (3)")[1].split("\n")[2]
    assert "c.php" in first


def test_max_symbols_limits_skeleton_md(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.php").write_text(
        "<?php\n" + "".join(f"function fn_{i}() {{}}\n" for i in range(10)), encoding="utf-8"
    )

    skeleton.handle(_ctx(tmp_path, {"skeleton": {"max_symbols": 2}}), {})

    text = (tmp_path / "ws/knowledge/skeleton/SKELETON.md").read_text(encoding="utf-8")
    assert "`fn_0`" in text and "`fn_1`" in text and "`fn_2`" not in text
    assert "+8" in text


def test_skeleton_exclude_config_alias(tmp_path):
    repo = _repo(tmp_path)

    skeleton.handle(_ctx(tmp_path, {"skeleton": {"exclude": ["mod"]}}), {})

    import json

    data = json.loads((tmp_path / "ws/knowledge/skeleton/project.json").read_text(encoding="utf-8"))
    assert data["files"] == 0


def test_notes_save_clip_reads_clipboard(tmp_path, monkeypatch):
    import sys
    import types

    from commands.complements.harness import notes

    repo = tmp_path / "repo"
    (repo / "m").mkdir(parents=True)
    (repo / "m" / "a.php").write_text("<?php\n", encoding="utf-8")
    meta = {"modulo": "m", "tags": [], "tabelas": [], "arquivos": ["m/a.php"],
            "hash_fonte": "", "revisado": False, "atualizado_em": ""}
    text = notes.render_note(meta, "# M\n\n" + notes.skeleton_body())
    fake = types.SimpleNamespace(paste=lambda: text)
    monkeypatch.setitem(sys.modules, "pyperclip", fake)

    result = notes_task.handle_save(_ctx(tmp_path), {"clip": True})

    assert result.success, result.summary
    assert (tmp_path / "ws/knowledge/notes/m.md").is_file()
