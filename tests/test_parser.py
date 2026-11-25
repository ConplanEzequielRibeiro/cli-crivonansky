"""Testes do parser de comandos (quoting e caminhos do Windows)."""

import os

import pytest

from core.parser import CommandParser


def test_quoted_question_is_one_argument():
    name, args = CommandParser.parse('/harness ask "como funciona o aluguel?"')

    assert name == "/harness"
    assert args == ["ask", "como funciona o aluguel?"]


def test_single_quotes_are_stripped():
    name, args = CommandParser.parse("/harness ask 'cadastro de cliente'")

    assert name == "/harness"
    assert args == ["ask", "cadastro de cliente"]


@pytest.mark.skipif(os.name != "nt", reason="caminhos do Windows")
def test_windows_backslashes_are_preserved():
    path = r"C:\projetos\harness-configs\meu-legado.yaml"

    name, args = CommandParser.parse(f"/harness --config {path} clean artifacts")

    assert name == "/harness"
    assert path in args


def test_empty_line():
    assert CommandParser.parse("   ") == (None, [])
