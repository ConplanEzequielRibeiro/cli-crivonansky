"""Testes das primitavas JIT (code:search/read/outline/symbol)."""

import json

from commands.complements.harness.runner import ProcessResult
from commands.complements.harness.tasks import jit
from commands.complements.harness.task_types import TaskContext


def _context(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cadastro").mkdir(parents=True)
    (repo / "cadastro" / "cliente.php").write_text(
        "<?php\n"
        "include '../includes/conexao.php';\n"
        "function salvar_cliente($dados) {\n"
        '    return "INSERT INTO tb_clientes (nome) VALUES (\'x\')";\n'
        "}\n"
        "salvar_cliente([]);\n",
        encoding="utf-8",
    )
    (repo / "app.js").write_text("function carregar() {}\n", encoding="utf-8")

    notes = tmp_path / "ws" / "knowledge" / "notes"
    notes.mkdir(parents=True)
    (notes / "clientes.md").write_text("# Clientes\n\nsalvar_cliente grava tb_clientes.\n", encoding="utf-8")

    return TaskContext(
        config={"legacy": {"repo_path": str(repo)}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def test_search_reports_unavailable_without_rg(tmp_path, monkeypatch):
    monkeypatch.setattr(jit, "rg_bin", lambda ctx: None)

    result = jit.handle_search(_context(tmp_path), {"pattern": "tb_clientes"})

    assert result.success is False
    assert result.status == "unavailable"
    assert "ripgrep" in result.summary


def test_search_parses_rg_json_and_truncates(tmp_path, monkeypatch):
    ctx = _context(tmp_path)
    repo = tmp_path / "repo"
    events = [
        {
            "type": "match",
            "data": {
                "path": {"text": str(repo / "cadastro" / "cliente.php")},
                "lines": {"text": "INSERT INTO tb_clientes\n"},
                "line_number": 4,
            },
        },
        {
            "type": "match",
            "data": {
                "path": {"text": str(repo / "cadastro" / "cliente.php")},
                "lines": {"text": "SELECT * FROM tb_clientes\n"},
                "line_number": 5,
            },
        },
    ]
    stdout = "\n".join(json.dumps(event) for event in events)

    monkeypatch.setattr(jit, "rg_bin", lambda ctx: "rg")
    monkeypatch.setattr(
        jit, "_run_rg", lambda ctx, pattern, roots, glob=None, encoding=None: ProcessResult(0, stdout, "")
    )

    result = jit.handle_search(ctx, {"pattern": "tb_clientes", "max_results": 1})

    assert result.success
    assert "2 ocorrência(s)" in result.summary
    assert "cadastro/cliente.php:4" in result.details
    assert "(truncado)" in result.details


def test_read_slices_lines_with_numbers(tmp_path):
    ctx = _context(tmp_path)

    result = jit.handle_read(
        ctx, {"file": "cadastro/cliente.php", "start": 3, "end": 5}
    )

    assert result.success
    assert "# cadastro/cliente.php:3-5 (total 6 linhas)" in result.details
    assert "function salvar_cliente" in result.details
    assert "salvar_cliente([])" not in result.details


def test_read_denies_path_outside_allowed_roots(tmp_path):
    ctx = _context(tmp_path)

    result = jit.handle_read(ctx, {"file": "../../README.md"})

    assert result.success is False
    assert result.status == "denied"


def test_outline_lists_symbols_and_imports(tmp_path):
    ctx = _context(tmp_path)

    result = jit.handle_outline(ctx, {"file": "cadastro/cliente.php"})

    assert result.success
    assert "## imports" in result.details
    assert "include '../includes/conexao.php'" in result.details
    assert "salvar_cliente" in result.details


def test_symbol_definitions_come_from_skeleton(tmp_path):
    ctx = _context(tmp_path)
    skeleton_dir = tmp_path / "ws" / "knowledge" / "skeleton"
    skeleton_dir.mkdir(parents=True)
    (skeleton_dir / "project.json").write_text(
        json.dumps(
            {
                "files_index": {
                    "cadastro/cliente.php": {
                        "symbols": [
                            {"name": "salvar_cliente", "line": 3, "end": 5, "kind": "function"}
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = jit.handle_symbol(ctx, {"name": "salvar_cliente", "kind": "def"})

    assert result.success
    assert "cadastro/cliente.php:3-5 (function)" in result.details


def test_symbol_references_use_rg(tmp_path, monkeypatch):
    ctx = _context(tmp_path)
    repo = tmp_path / "repo"
    stdout = json.dumps(
        {
            "type": "match",
            "data": {
                "path": {"text": str(repo / "cadastro" / "cliente.php")},
                "lines": {"text": "salvar_cliente([]);\n"},
                "line_number": 6,
            },
        }
    )
    monkeypatch.setattr(jit, "rg_bin", lambda ctx: "rg")
    monkeypatch.setattr(
        jit, "_run_rg", lambda ctx, pattern, roots, glob=None, encoding=None: ProcessResult(0, stdout, "")
    )

    result = jit.handle_symbol(ctx, {"name": "salvar_cliente", "kind": "ref"})

    assert result.success
    assert "cadastro/cliente.php:6" in result.details
    assert "1 referência(s)" in result.summary
