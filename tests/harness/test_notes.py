"""Fichas: esquema, notes:draft/save/stale, notes_path e config (T12–T16)."""

import os

import pytest

from commands.complements.harness import notes, ops
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import notes as notes_task
from commands.complements.harness.tasks import skeleton, env
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
    (folder / "veiculo.php").write_text(
        '<?php\r\nfunction salvar_veiculo() {\r\n mysql_query("SELECT * FROM tb_veiculos");\r\n}\r\n',
        encoding="utf-8",
    )
    (folder / "marca.php").write_text("<?php\r\nfunction listar_marcas() {}\r\n", encoding="utf-8")
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


# --- notes_path ---------------------------------------------------------------
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


# --- notes:save ---------------------------------------------------------------
def test_save_stamps_hash_and_writes_inside_notes_path(tmp_path, repo):
    ctx = _ctx(tmp_path)

    result = notes_task.handle_save(ctx, {"content": _valid()})

    assert result.success, result.summary
    saved = tmp_path / "ws" / "knowledge" / "notes" / "cadastro.md"
    meta, _ = notes.split_note(saved.read_text(encoding="utf-8"))
    assert meta["hash_fonte"] == notes.source_hash(str(repo), ["cadastro/veiculo.php"])
    assert meta["atualizado_em"] != "2026-01-01"
    assert "\r" not in saved.read_text(encoding="utf-8")


def test_save_rejects_invalid_note_and_path_escape(tmp_path, repo):
    ctx = _ctx(tmp_path)

    assert not notes_task.handle_save(ctx, {"content": "sem frontmatter"}).success
    assert not notes_task.handle_save(ctx, {}).success

    # o nome do arquivo vem do slug do módulo: nunca escapa de notes_path
    result = notes_task.handle_save(ctx, {"content": _valid(modulo="../../etc/x")})
    assert result.success
    saved = os.path.join(notes_path(ctx), "etc-x.md")
    assert os.path.isfile(saved)


def test_save_preview_shows_diff_for_existing_note(tmp_path, repo):
    ctx = _ctx(tmp_path)
    notes_task.handle_save(ctx, {"content": _valid()})

    changed = _valid().replace("# Cadastro", "# Cadastro de veículos")
    preview = notes_task.preview_save(_ctx(tmp_path), {"content": changed})

    assert "-# Cadastro" in preview and "+# Cadastro de veículos" in preview


def test_save_accepts_fenced_block_and_strips_draft_context(tmp_path, repo):
    ctx = _ctx(tmp_path)
    text = "```markdown\n" + _valid() + "\n## Material levantado (apague)\n\n- x\n```"

    result = notes_task.handle_save(ctx, {"content": text})

    assert result.success, result.summary
    saved = (tmp_path / "ws" / "knowledge" / "notes" / "cadastro.md").read_text(encoding="utf-8")
    assert "Material levantado" not in saved


# --- notes:draft / notes:stale -------------------------------------------------
def test_draft_is_valid_per_schema_and_has_instruction(tmp_path, repo):
    ctx = _ctx(tmp_path)
    skeleton.handle(ctx, {})

    result = notes_task.handle_draft(ctx, {"module": "cadastro"})

    assert result.success, result.summary
    assert "tb_veiculos" in result.details
    assert "Complete as seções" in result.details
    notes.parse_note(notes_task._strip_context(result.details.split("\n---\nComplete")[0].split("\n## Material levantado")[0]))


def test_draft_requires_skeleton_and_known_module(tmp_path, repo):
    ctx = _ctx(tmp_path)
    assert "esqueleto ainda não gerado" in notes_task.handle_draft(ctx, {"module": "cadastro"}).summary

    skeleton.handle(ctx, {})
    assert not notes_task.handle_draft(ctx, {"module": "nada"}).success
    assert not notes_task.handle_draft(ctx, {}).success


def test_stale_lists_note_after_source_change(tmp_path, repo):
    ctx = _ctx(tmp_path)
    notes_task.handle_save(ctx, {"content": _valid()})
    assert notes_task.handle_stale(ctx, {}).summary.startswith("0 ficha(s)")

    path = repo / "cadastro" / "veiculo.php"
    path.write_text(path.read_text(encoding="utf-8") + "// alterado\r\n", encoding="utf-8")

    result = notes_task.handle_stale(ctx, {})

    assert result.summary.startswith("1 ficha(s)")
    assert "cadastro.md" in result.details
    assert "cadastro/veiculo.php" in result.details


def test_stale_reports_invalid_notes_and_empty_folder(tmp_path, repo):
    ctx = _ctx(tmp_path)
    assert "nenhuma ficha" in notes_task.handle_stale(ctx, {}).summary

    folder = tmp_path / "ws" / "knowledge" / "notes"
    folder.mkdir(parents=True)
    (folder / "ruim.md").write_text("sem frontmatter", encoding="utf-8")
    (folder / "_modelo.md").write_text(notes.model_text(), encoding="utf-8")

    result = notes_task.handle_stale(ctx, {})

    assert "Fichas inválidas (1)" in result.details
    assert "_modelo" not in result.details
