"""kb:export (T24): MAPA, glossário, ADRs, fichas revisadas, redact e MANIFEST."""

import json

from commands.complements.harness import notes
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import kb


def _ctx(tmp_path, extra=None):
    config = {"legacy": {"repo_path": str(tmp_path / "repo")}}
    config.update(extra or {})
    return TaskContext(config=config, workspace=str(tmp_path / "ws"), run_dir=str(tmp_path / "run"))


def _seed(tmp_path):
    ws = tmp_path / "ws" / "knowledge"
    (ws / "skeleton").mkdir(parents=True)
    (ws / "skeleton" / "MAP.md").write_text("# Mapa\n- cadastro/\n", encoding="utf-8")
    folder = ws / "notes"
    (folder / "adr").mkdir(parents=True)
    (folder / "glossario.md").write_text("# Glossário\nSGG: sistema. Contato a@b.com.br\n", encoding="utf-8")
    (folder / "adr" / "0001.md").write_text("# ADR 1\nUsar PDO.\n", encoding="utf-8")

    def note(name, revisado):
        meta = {"modulo": name, "tags": [], "tabelas": [], "arquivos": [], "hash_fonte": "x",
                "revisado": revisado, "atualizado_em": "2026-01-01"}
        (folder / f"{name}.md").write_text(notes.render_note(meta, "# T\n\n" + notes.skeleton_body()), encoding="utf-8")

    note("revisada", True)
    note("rascunho", False)
    return ws


def test_export_includes_reviewed_only_masks_and_writes_manifest(tmp_path):
    _seed(tmp_path)

    result = kb.handle(_ctx(tmp_path), {})

    assert result.success, result.summary
    out = tmp_path / "ws" / "kb_export"
    assert (out / "MAPA.md").is_file() and (out / "adr" / "0001.md").is_file()
    assert (out / "fichas" / "revisada.md").is_file()
    assert not (out / "fichas" / "rascunho.md").exists()
    assert "a@b.com.br" not in (out / "glossario.md").read_text(encoding="utf-8")
    manifest = (out / "MANIFEST.md").read_text(encoding="utf-8")
    assert "| MAPA.md | novo |" in manifest and "email=1" in manifest


def test_second_export_reports_changes_and_removals(tmp_path):
    ws = _seed(tmp_path)
    kb.handle(_ctx(tmp_path), {})

    (ws / "skeleton" / "MAP.md").write_text("# Mapa v2\n", encoding="utf-8")
    (ws / "notes" / "adr" / "0001.md").unlink()
    result = kb.handle(_ctx(tmp_path), {})

    manifest = (tmp_path / "ws" / "kb_export" / "MANIFEST.md").read_text(encoding="utf-8")
    assert "| MAPA.md | alterado |" in manifest
    assert "| glossario.md | igual |" in manifest
    assert "Removidos desde a última exportação: adr/0001.md" in manifest
    assert not (tmp_path / "ws" / "kb_export" / "adr" / "0001.md").exists()
    assert json.loads((tmp_path / "ws" / "kb_export" / ".manifest.json").read_text())["files"]


def test_size_limit_omits_lowest_priority_and_says_so(tmp_path):
    _seed(tmp_path)

    result = kb.handle(_ctx(tmp_path), {"max_chars": 120})

    manifest = (tmp_path / "ws" / "kb_export" / "MANIFEST.md").read_text(encoding="utf-8")
    assert "Omitidos pelo limite de tamanho" in manifest
    assert "fichas/revisada.md" in manifest.split("Omitidos")[1]
    assert (tmp_path / "ws" / "kb_export" / "MAPA.md").is_file()
    assert "omitido(s)" in result.summary


def test_nothing_to_export_fails_with_hint(tmp_path):
    result = kb.handle(_ctx(tmp_path), {})

    assert not result.success and result.hint
