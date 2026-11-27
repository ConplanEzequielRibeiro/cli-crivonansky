"""Esquema de fichas (`notes.py`), `notes_path` e config (T12–T16).

As tarefas `notes:draft/save/stale` foram removidas na R0.2; o esquema permanece
temporariamente porque `state` (slugify) e `watch` ainda o usam até a R0.8.
"""

import pytest

from commands.complements.harness import notes, ops
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import env
from commands.complements.harness.util import allowed_roots, notes_path


def _ctx(tmp_path, knowledge=None):
    config = {"legacy": {"repo_path": str(tmp_path / "repo")}}
    if knowledge is not None:
        config["knowledge"] = knowledge
    return TaskContext(config=config, workspace=str(tmp_path / "ws"), run_dir=str(tmp_path / "run"))


@pytest.fixture
def repo(tmp_path):
    folder = tmp_path / "repo" / "cadastro"
    folder.mkdir(parents=True)
    # write_bytes: no Windows, write_text traduz "\n" para "\r\n" e duplicaria o CR.
    (folder / "veiculo.php").write_bytes(
        b'<?php\r\nfunction salvar_veiculo() {\r\n mysql_query("SELECT * FROM tb_veiculos");\r\n}\r\n'
    )
    (folder / "marca.php").write_bytes(b"<?php\r\nfunction listar_marcas() {}\r\n")
    return tmp_path / "repo"


def _valid(modulo="cadastro", arquivos=("cadastro/veiculo.php",), hash_fonte="x"):
    meta = {
        "modulo": modulo,
        "tags": ["veiculo"],
        "tabelas": ["tb_veiculos"],
        "arquivos": list(arquivos),
        "hash_fonte": hash_fonte,
        "revisado": True,
        "atualizado_em": "2026-01-01",
    }
    return notes.render_note(meta, "# Cadastro\n\n" + notes.skeleton_body())


# --- esquema ----------------------------------------------------------------
def test_model_is_valid_and_missing_field_is_rejected():
    notes.parse_note(notes.model_text())

    broken = notes.model_text().replace("tabelas: []\n", "")
    with pytest.raises(notes.NoteError, match="campo obrigatório ausente: tabelas"):
        notes.parse_note(broken)


def test_rejects_missing_section_and_escaping_path():
    text = _valid().replace("## Armadilhas", "## Outra")
    with pytest.raises(notes.NoteError, match="seção ausente: ## Armadilhas"):
        notes.parse_note(text)

    with pytest.raises(notes.NoteError, match="fora do repositório"):
        notes.parse_note(_valid(arquivos=("../x.php",)))


def test_source_hash_ignores_eol_and_detects_change(repo):
    first = notes.source_hash(str(repo), ["cadastro/veiculo.php"])
    path = repo / "cadastro" / "veiculo.php"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    assert notes.source_hash(str(repo), ["cadastro/veiculo.php"]) == first

    path.write_text(path.read_text() + "// novo\n", encoding="utf-8")
    assert notes.source_hash(str(repo), ["cadastro/veiculo.php"]) != first


# --- notes_path -------------------------------------------------------------
def test_notes_path_default_and_configured(tmp_path):
    assert notes_path(_ctx(tmp_path)) == str(tmp_path / "ws" / "knowledge" / "notes")

    external = tmp_path / "notas-repo"
    ctx = _ctx(tmp_path, {"notes_path": str(external)})
    assert notes_path(ctx) == str(external)
    assert str(external) in allowed_roots(ctx)


def test_env_check_warns_when_notes_path_is_not_git(tmp_path, repo):
    external = tmp_path / "notas-repo"
    external.mkdir()
    ctx = _ctx(tmp_path, {"notes_path": str(external)})

    result = env.handle(ctx, {})

    assert "não é um repositório git" in result.details


def test_config_info_shows_notes_path_and_exclude(tmp_path):
    config = {
        "workspace": str(tmp_path / "ws"),
        "knowledge": {"notes_path": str(tmp_path / "n")},
        "legacy": {"exclude": ["vendor", "*.bak.php"]},
    }
    info = {}
    ops._add_profile_info(info, config)

    assert info["notes_path"] == str(tmp_path / "n")
    assert info["exclude"] == "vendor, *.bak.php"
