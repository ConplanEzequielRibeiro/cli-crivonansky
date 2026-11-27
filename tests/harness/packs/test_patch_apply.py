"""patch:apply — preserva encoding/CRLF/BOM e exige branch de trabalho (T05/T06)."""

import subprocess

import pytest

from commands.complements.harness import patching
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import patch as patch_task

ORIGINAL = "<?php\r\n// Ação\r\n$a = 1;\r\necho $a;\r\n"
DIFF = """diff --git a/cadastro/x.php b/cadastro/x.php
--- a/cadastro/x.php
+++ b/cadastro/x.php
@@ -1,4 +1,5 @@
 <?php
 // Ação
-$a = 1;
+$a = 2; // coração
+$b = 3;
 echo $a;
"""


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "cadastro").mkdir(parents=True)
    (root / "cadastro" / "x.php").write_bytes(ORIGINAL.encode("latin-1"))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _ctx(tmp_path, repo, extra=None):
    config = {"legacy": {"repo_path": str(repo), "encoding": "latin-1"}}
    config.update(extra or {})
    return TaskContext(config=config, workspace=str(tmp_path / "ws"), run_dir=str(tmp_path / "run"))


def test_refuses_protected_branch(tmp_path, repo):
    result = patch_task.handle(_ctx(tmp_path, repo), {"diff": DIFF})

    assert not result.success
    assert "protegida" in result.summary
    assert (repo / "cadastro" / "x.php").read_bytes() == ORIGINAL.encode("latin-1")


def test_applies_in_latin1_crlf_on_new_branch(tmp_path, repo):
    result = patch_task.handle(_ctx(tmp_path, repo), {"diff": DIFF, "branch": "ajuste"})

    assert result.success, result.details
    data = (repo / "cadastro" / "x.php").read_bytes()
    assert data == "<?php\r\n// Ação\r\n$a = 2; // coração\r\n$b = 3;\r\necho $a;\r\n".encode("latin-1")
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert branch == "ajuste"
    assert "latin-1, CRLF" in result.details


def test_refuses_dirty_target(tmp_path, repo):
    (repo / "cadastro" / "x.php").write_bytes(ORIGINAL.encode("latin-1") + b"// sujo\r\n")

    result = patch_task.handle(_ctx(tmp_path, repo), {"diff": DIFF, "branch": "ajuste"})

    assert not result.success
    assert "não commitadas" in result.summary


def test_reports_context_mismatch(tmp_path, repo):
    bad = DIFF.replace("echo $a;", "echo $zzz;")

    result = patch_task.handle(_ctx(tmp_path, repo), {"diff": bad, "branch": "ajuste"})

    assert not result.success
    assert "não se aplica" in result.summary


def test_rejects_path_outside_repo(tmp_path, repo):
    evil = DIFF.replace("cadastro/x.php", "../fora.php")

    result = patch_task.handle(_ctx(tmp_path, repo), {"diff": evil, "branch": "ajuste"})

    assert not result.success
    assert "fora do repositório" in result.summary


def test_unencodable_character_fails_clearly(tmp_path, repo):
    emoji = DIFF.replace("coração", "ok \U0001F600")

    result = patch_task.handle(_ctx(tmp_path, repo), {"diff": emoji, "branch": "ajuste"})

    assert not result.success
    assert "latin-1" in result.summary


def test_preserves_utf8_bom(tmp_path, repo):
    path = repo / "cadastro" / "u.php"
    path.write_bytes(b"\xef\xbb\xbf<?php\r\necho 1;\r\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "u")
    diff = (
        "--- a/cadastro/u.php\n+++ b/cadastro/u.php\n@@ -1,2 +1,2 @@\n <?php\n-echo 1;\n+echo 2;\n"
    )

    result = patch_task.handle(_ctx(tmp_path, repo), {"diff": diff, "branch": "b"})

    assert result.success, result.details
    assert path.read_bytes() == b"\xef\xbb\xbf<?php\r\necho 2;\r\n"


def test_new_file_follows_neighbours_eol(tmp_path, repo):
    diff = "--- /dev/null\n+++ b/cadastro/novo.php\n@@ -0,0 +1,2 @@\n+<?php\n+// Ação\n"

    result = patch_task.handle(_ctx(tmp_path, repo), {"diff": diff, "branch": "b"})

    assert result.success, result.details
    assert (repo / "cadastro" / "novo.php").read_bytes() == "<?php\r\n// Ação\r\n".encode("latin-1")


def test_detect_format_variants():
    assert patching.detect_format(b"a\r\nb\r\n").eol == "crlf"
    assert patching.detect_format(b"a\nb\n").eol == "lf"
    assert patching.detect_format(b"a\r\nb\n").eol == "mixed"
    assert patching.detect_format(b"\xef\xbb\xbfa\n").bom
    assert patching.detect_format("Ação\n".encode("latin-1"), "latin-1").encoding == "latin-1"
