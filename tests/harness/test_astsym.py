"""Testes da extração de símbolos por linguagem (ast-grep + fallback)."""

from commands.complements.harness import astsym


def _names(source: str, path: str) -> set[str]:
    return {item["name"] for item in astsym.definitions(source, path)}


def test_java_definitions_and_imports():
    source = (
        "package x;\n"
        "import java.util.List;\n"
        "public class Foo {\n"
        "  public int bar(int x) { return x; }\n"
        "}\n"
    )

    assert {"Foo", "bar"} <= _names(source, "Foo.java")
    assert astsym.extract_imports(source, "Foo.java") == ["import java.util.List;"]


def test_csharp_definitions_and_using():
    source = (
        "using System;\n"
        "namespace N {\n"
        "  public class Foo {\n"
        "    public int Bar(int x) { return x; }\n"
        "  }\n"
        "}\n"
    )

    assert {"Foo", "Bar"} <= _names(source, "Foo.cs")
    assert astsym.extract_imports(source, "Foo.cs") == ["using System;"]


def test_ruby_definitions():
    source = (
        "class Foo\n"
        "  def bar(x)\n"
        "    x\n"
        "  end\n"
        "  def self.criar\n"
        "  end\n"
        "end\n"
    )

    assert {"Foo", "bar", "criar"} <= _names(source, "foo.rb")


def test_go_definitions():
    source = (
        "package main\n"
        "type Foo struct { N int }\n"
        "func (f Foo) Bar(x int) int { return x }\n"
        "func solta() {}\n"
    )

    assert {"Foo", "Bar", "solta"} <= _names(source, "main.go")


def test_kotlin_definitions():
    source = "class Foo {\n  fun bar(x: Int): Int { return x }\n}\n"

    assert {"Foo", "bar"} <= _names(source, "Foo.kt")


def test_scala_definitions():
    source = "class Foo {\n  def bar(x: Int): Int = x\n}\nobject Utils {\n  def qux(): Unit = {}\n}\n"

    assert {"Foo", "Utils", "bar", "qux"} <= _names(source, "Foo.scala")


def test_cpp_definitions():
    source = (
        "class Foo { public: void bar(); };\n"
        "int soma(int a, int b) { return a + b; }\n"
    )

    assert {"Foo", "bar", "soma"} <= _names(source, "foo.cpp")


def test_unknown_language_does_not_panic():
    # `c_sharp` derruba o processo (PanicException) se chegar ao parser.
    result = astsym._definitions_ast(
        "class X {}", "c_sharp", {"class_declaration": "class"}
    )

    assert result is None


def test_java_fallback_without_ast_grep(monkeypatch):
    monkeypatch.setattr(astsym, "ast_grep", lambda: None)
    source = "public class Foo {\n  public int bar(int x) { return x; }\n}\n"

    names = _names(source, "Foo.java")

    assert {"Foo", "bar"} <= names


def test_ruby_fallback_uses_indentation(monkeypatch):
    monkeypatch.setattr(astsym, "ast_grep", lambda: None)
    source = "class Foo\n  def bar\n    1\n  end\nend\n"

    found = astsym.definitions(source, "foo.rb")
    bar = next(item for item in found if item["name"] == "bar")

    assert bar["end"] >= bar["line"]
