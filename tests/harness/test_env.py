from commands.complements.harness.runner import ProcessResult
from commands.complements.harness.tasks import env
from commands.complements.harness.task_types import TaskContext


def _context(tmp_path):
    rag = tmp_path / "rag"
    rag.mkdir()
    (rag / "main.py").write_text("print('rag')\n", encoding="utf-8")
    python = rag / "python.exe"
    python.write_text("", encoding="utf-8")

    return TaskContext(
        config={
            "tools": {
                "rag": {
                    "path": str(rag),
                    "python": str(python),
                }
            }
        },
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def test_env_check_reports_missing_executable_without_crashing(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError(2, "O sistema nao pode encontrar o arquivo especificado")

    monkeypatch.setattr(env, "run_process", boom)

    result = env.handle(_context(tmp_path), {})

    assert result.success is False
    assert "git" in result.details
    assert "não foi possível executar" in result.details
    assert "traceback" not in result.details.lower()


def test_env_check_reports_missing_rag_python(tmp_path, monkeypatch):
    ctx = _context(tmp_path)
    ctx.config["tools"]["rag"]["python"] = str(tmp_path / "sumiu" / "python.exe")
    monkeypatch.setattr(
        env,
        "run_process",
        lambda cmd, timeout=15: ProcessResult(0, f"{cmd[0]} ok", ""),
    )

    result = env.handle(ctx, {})

    assert result.success is False
    assert "Python do RAG não encontrado" in result.details


def test_env_check_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(
        env,
        "run_process",
        lambda cmd, timeout=15: ProcessResult(0, f"{cmd[0]} ok", ""),
    )
    monkeypatch.setattr(env, "_http_ok", lambda *a, **k: (True, "ok"))

    result = env.handle(_context(tmp_path), {})

    assert result.success is True
    assert "ambiente OK" in result.summary
    assert "rag (tools.rag)" in result.details
    assert "workspace" in result.details


def test_env_check_reports_profile_and_file_count(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.php").write_text("<?php\n", encoding="utf-8")
    (repo / "app.js").write_text("var a = 1;\n", encoding="utf-8")

    ctx = _context(tmp_path)
    ctx.config["legacy"] = {"repo_path": str(repo)}
    monkeypatch.setattr(
        env,
        "run_process",
        lambda cmd, timeout=15: ProcessResult(0, f"{cmd[0]} ok", ""),
    )
    monkeypatch.setattr(env, "_http_ok", lambda *a, **k: (True, "ok"))

    result = env.handle(ctx, {})

    assert result.success is True
    assert "perfil" in result.details
    assert "php-mysql" in result.details
    assert "arquivos do perfil" in result.details
    assert "2 arquivo(s)" in result.details


def test_env_check_warns_when_profile_finds_no_files(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "App.java").write_text("class App {}\n", encoding="utf-8")

    ctx = _context(tmp_path)
    ctx.config["legacy"] = {"repo_path": str(repo)}
    monkeypatch.setattr(
        env,
        "run_process",
        lambda cmd, timeout=15: ProcessResult(0, f"{cmd[0]} ok", ""),
    )
    monkeypatch.setattr(env, "_http_ok", lambda *a, **k: (True, "ok"))

    result = env.handle(ctx, {})

    assert result.success is True
    assert "AVISO: nenhum arquivo" in result.details


def test_env_check_reports_unknown_stack(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    ctx = _context(tmp_path)
    ctx.config["legacy"] = {"repo_path": str(repo), "stack": "cobol"}
    monkeypatch.setattr(
        env,
        "run_process",
        lambda cmd, timeout=15: ProcessResult(0, f"{cmd[0]} ok", ""),
    )
    monkeypatch.setattr(env, "_http_ok", lambda *a, **k: (True, "ok"))

    result = env.handle(ctx, {})

    assert result.success is False
    assert "legacy.stack" in result.details
