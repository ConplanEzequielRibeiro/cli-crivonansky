"""Manifesto de frescor: escrita, verificação e integração (M0)."""

import os
import subprocess

from commands.complements.harness import manifest
from commands.complements.harness_core.task_types import TaskContext
from commands.complements.harness.tasks import knowledge, links, skeleton


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Teste")
    (repo / "a.php").write_text("<?php\nfunction a() {}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


def _ctx(tmp_path, repo):
    return TaskContext(
        config={"legacy": {"repo_path": str(repo)}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def _index(repo):
    index = {}
    for path in repo.rglob("*.php"):
        rel = path.relative_to(repo).as_posix()
        stat = path.stat()
        index[rel] = {"size": stat.st_size, "mtime": int(stat.st_mtime)}
    return index


def _write(ctx, repo, index):
    project = os.path.join(ctx.workspace, "knowledge", "skeleton", "project.json")
    os.makedirs(os.path.dirname(project), exist_ok=True)
    with open(project, "w", encoding="utf-8") as fh:
        fh.write("{}\n")
    return manifest.write_manifest(
        ctx,
        {"knowledge/skeleton/project.json": {"files": len(index)}},
        manifest.inputs_from_index(ctx, index),
        "php-mysql",
        3,
    )


def test_fresh_stale_and_dirty(tmp_path):
    repo = _repo(tmp_path)
    ctx = _ctx(tmp_path, repo)
    _write(ctx, repo, _index(repo))

    assert manifest.verify(ctx)["status"] == "fresh"

    (repo / "a.php").write_text("<?php\nfunction a() { return 1; }\n", encoding="utf-8")
    assert manifest.verify(ctx)["status"] == "stale"

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "change")
    _write(ctx, repo, _index(repo))
    (repo / "novo.txt").write_text("untracked", encoding="utf-8")
    assert manifest.verify(ctx)["status"] == "dirty"
    assert manifest.verify(ctx, fail_on_dirty=True)["ok"] is False


def test_deep_detects_same_size_change_with_restored_mtime(tmp_path):
    repo = _repo(tmp_path)
    (repo / "b.php").write_text("<?php\n//aaa\n", encoding="utf-8")
    (repo / ".gitignore").write_text("b.php\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore b")
    ctx = _ctx(tmp_path, repo)
    _write(ctx, repo, _index(repo))

    path = repo / "b.php"
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b"aaa", b"bbb"))
    os.utime(path, (stat.st_atime, stat.st_mtime))

    assert manifest.verify(ctx)["status"] == "fresh"
    assert manifest.verify(ctx, deep=True)["status"] == "stale"


def test_no_git_is_unknown(tmp_path):
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "a.php").write_text("<?php\n", encoding="utf-8")
    ctx = _ctx(tmp_path, repo)
    _write(ctx, repo, _index(repo))

    data = manifest.verify(ctx)

    assert data["status"] == "unknown"
    assert data["ok"] is False


def test_missing_manifest_is_unknown(tmp_path):
    repo = _repo(tmp_path)
    ctx = _ctx(tmp_path, repo)

    data = manifest.verify(ctx)

    assert data["status"] == "unknown"
    assert "manifesto ausente" in data["reasons"][0]


def test_skeleton_and_links_update_manifest(tmp_path):
    repo = _repo(tmp_path)
    (repo / "b.php").write_text('<?php mysql_query("SELECT * FROM tb_x");\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "sql")
    ctx = _ctx(tmp_path, repo)

    assert skeleton.handle(ctx, {}).success
    info = manifest.read_manifest(ctx)
    assert info["schema"] == manifest.SCHEMA
    assert "knowledge/skeleton/project.json" in info["artifacts"]
    assert any(item["path"] == "a.php" for item in info["inputs"])

    assert links.handle(ctx, {}).success
    info = manifest.read_manifest(ctx)
    assert "knowledge/links/code-db-links.json" in info["artifacts"]


def test_knowledge_verify_task_reports_staleness(tmp_path):
    repo = _repo(tmp_path)
    ctx = _ctx(tmp_path, repo)
    skeleton.handle(ctx, {})

    assert knowledge.handle(ctx, {}).success

    (repo / "a.php").write_text("<?php\nfunction a() { return 2; }\n", encoding="utf-8")
    result = knowledge.handle(ctx, {})

    assert result.success is False
    assert "stale" in result.summary
