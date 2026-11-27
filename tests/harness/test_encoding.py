"""Testes de encoding do legado (legacy.encoding) — F6.6."""

import pytest

from commands.complements.harness_core.runner import ProcessResult
from commands.complements.harness.tasks import jit, links
from commands.complements.harness_core.task_types import TaskContext
from commands.complements.harness_core.util import read_text


def _ctx(tmp_path, legacy=None):
    return TaskContext(
        config={"legacy": {"repo_path": str(tmp_path / "repo"), **(legacy or {})}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def test_read_text_falls_back_to_cp1252(tmp_path):
    path = tmp_path / "legado.txt"
    path.write_bytes("Ação de cadastro".encode("cp1252"))

    assert read_text(str(path)) == "Ação de cadastro"


def test_read_text_keeps_utf8(tmp_path):
    path = tmp_path / "utf8.txt"
    path.write_text("Ação de cadastro", encoding="utf-8")

    assert read_text(str(path)) == "Ação de cadastro"


def test_read_text_honors_configured_encoding(tmp_path):
    path = tmp_path / "latin.txt"
    path.write_bytes("Situação".encode("latin-1"))

    assert read_text(str(path), "latin-1") == "Situação"


def test_rg_encoding_mapping():
    assert jit._rg_encoding("cp1252") == "windows-1252"
    assert jit._rg_encoding("latin-1") == "windows-1252"
    assert jit._rg_encoding("utf-8") is None
    assert jit._rg_encoding(None) is None


def test_run_rg_passes_encoding_flag(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, {"encoding": "cp1252"})
    captured = {}

    def fake_run(cmd, timeout=60, env=None):
        captured["cmd"] = cmd
        return ProcessResult(0, "", "")

    monkeypatch.setattr(jit, "rg_bin", lambda ctx: "rg")
    monkeypatch.setattr(jit, "run_process", fake_run)

    jit._run_rg(ctx, "tb_x", [str(tmp_path)], encoding="cp1252")

    assert "--encoding" in captured["cmd"]
    assert "windows-1252" in captured["cmd"]


def test_code_read_decodes_cp1252(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "cadastro.php").write_bytes(
        "<?php\n// Ação de cadastro\n".encode("cp1252")
    )
    ctx = _ctx(tmp_path, {"encoding": "cp1252"})
    ctx.config["legacy"]["repo_path"] = str(repo)

    result = jit.handle_read(ctx, {"file": "cadastro.php", "start": 1, "end": 3})

    assert result.success
    assert "Ação de cadastro" in result.details


def test_links_decodes_cp1252(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "cadastro.php").write_bytes(
        (
            "<?php\n"
            "$sql = \"INSERT INTO tb_clientes (nome) VALUES ('Ação')\";\n"
        ).encode("cp1252")
    )
    ctx = _ctx(tmp_path, {"encoding": "cp1252"})
    ctx.config["legacy"]["repo_path"] = str(repo)

    result = links.handle(ctx, {})

    assert result.success
    data = (tmp_path / "ws" / "knowledge" / "links" / "code-db-links.json").read_text(
        encoding="utf-8"
    )
    assert "tb_clientes" in data


@pytest.mark.parametrize("encoding", ["cp1252", "latin-1"])
def test_profile_encoding_reaches_tasks(tmp_path, encoding):
    ctx = _ctx(tmp_path, {"stack": "custom", "encoding": encoding})

    from commands.complements.harness.profiles import resolve_profile

    assert resolve_profile(ctx.config).encoding == encoding
