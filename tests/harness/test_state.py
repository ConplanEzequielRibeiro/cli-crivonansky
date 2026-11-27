"""state:save / state:load / state:list (T21)."""

import pytest

from commands.complements.harness import state as st
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import state as state_task

BLOCK = """Aqui vai o estado:

```crivonansky-state
tarefa: Ajuste do cadastro de veículo
decisoes:
  - manter mysql_* neste módulo
arquivos:
  - cadastro/veiculo.php
pendencias:
  - validar placa antiga
proximo_passo: ler salvar_veiculo() e propor o patch
```
"""


def _ctx(tmp_path):
    return TaskContext(config={"legacy": {"repo_path": str(tmp_path / "repo")}},
                       workspace=str(tmp_path / "ws"), run_dir=str(tmp_path / "run"))


def test_parse_rejects_missing_fields_and_bad_paths():
    with pytest.raises(st.StateError, match="campo obrigatório ausente: pendencias"):
        st.parse_state("```crivonansky-state\ntarefa: x\ndecisoes: []\narquivos: []\nproximo_passo: y\n```")
    with pytest.raises(st.StateError, match="fora do repositório"):
        st.parse_state(BLOCK.replace("cadastro/veiculo.php", "../x.php"))
    with pytest.raises(st.StateError):
        st.parse_state("texto solto")


def test_save_then_load_rebuilds_resume_prompt(tmp_path):
    ctx = _ctx(tmp_path)
    map_dir = tmp_path / "ws" / "knowledge" / "skeleton"
    map_dir.mkdir(parents=True)
    (map_dir / "MAP.md").write_text("# Mapa do código\n- cadastro/", encoding="utf-8")

    saved = state_task.handle_save(ctx, {"content": BLOCK})
    assert saved.success, saved.summary
    assert "ajuste-do-cadastro-de-veiculo" in saved.summary

    loaded = state_task.handle_load(ctx, {"name": "last"})

    assert loaded.success
    for expected in ("manter mysql_* neste módulo", "cadastro/veiculo.php",
                     "validar placa antiga", "ler salvar_veiculo()", "# Mapa do código"):
        assert expected in loaded.details
    assert "crivonansky" in loaded.details


def test_migrates_legacy_notes_state(tmp_path):
    legacy = tmp_path / "legacy-notas" / "estado"
    legacy.mkdir(parents=True)
    (legacy / "old.md").write_text("---\ntarefa: x\n---\n", encoding="utf-8")
    ctx = TaskContext(
        config={
            "legacy": {"repo_path": str(tmp_path / "repo")},
            "knowledge": {"notes_path": str(tmp_path / "legacy-notas")},
        },
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )

    result = state_task.handle_list(ctx, {})

    assert "1 estado(s)" == result.summary
    assert (tmp_path / "ws" / "state" / "estado" / "old.md").is_file()


def test_save_stays_inside_state_path_and_list(tmp_path):
    ctx = _ctx(tmp_path)
    assert "nenhum estado" in state_task.handle_list(ctx, {}).summary
    state_task.handle_save(ctx, {"content": BLOCK.replace("Ajuste do cadastro de veículo", "../../fuga")})

    result = state_task.handle_list(ctx, {})

    assert "1 estado(s)" == result.summary
    assert (tmp_path / "ws" / "state" / "estado").is_dir()
    assert not (tmp_path / "fuga.md").exists()


def test_load_by_partial_name_and_missing(tmp_path):
    ctx = _ctx(tmp_path)
    state_task.handle_save(ctx, {"content": BLOCK})

    assert state_task.handle_load(ctx, {"name": "veiculo"}).success
    assert not state_task.handle_load(ctx, {"name": "inexistente"}).success


def test_preview_shows_new_then_diff(tmp_path):
    ctx = _ctx(tmp_path)
    assert "Novo estado" in state_task.preview_save(ctx, {"content": BLOCK})
    state_task.handle_save(ctx, {"content": BLOCK})

    changed = BLOCK.replace("validar placa antiga", "placa validada")
    assert "+- placa validada" in state_task.preview_save(_ctx(tmp_path), {"content": changed})
