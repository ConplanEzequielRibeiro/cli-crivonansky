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


def test_php_mixed_html_keeps_code_after_html():
    # Tags PHP dentro de strings de <script> e de comentários HTML confundiam o
    # parser: o código depois do HTML era ignorado.
    source = (
        "<?php\n"
        "function listar() {\n"
        '    $sql = "SELECT * FROM tb_veiculos";\n'
        "?>\n"
        "<script>var x = '<?php echo 1; ?>';</script>\n"
        "<!-- <div><?php echo 2; ?></div> -->\n"
        "<?php\n"
        "}\n"
        "class Cadastro {\n"
        "    public function salvar() {\n"
        "?>\n"
        "<form>a</form>\n"
        "<?php\n"
        "    }\n"
        "    public function depois() { return 1; }\n"
        "}\n"
    )

    found = {item["name"] for item in astsym.definitions(source, "mixed.php")}

    assert {"listar", "Cadastro", "salvar", "depois"} <= found


def test_php_code_only_masks_html_and_preserves_lines():
    source = (
        "<?php function a() {}\n"
        "?>\n"
        "<p>{ nao conta }</p>\n"
        "<?php\n"
        "function b() {}\n"
    )

    masked = astsym.php_code_only(source)

    assert masked.count("\n") == source.count("\n")
    assert "function b" in masked
    assert "<p>" not in masked


def test_php_imports_ignore_html(monkeypatch):
    monkeypatch.setattr(astsym, "ast_grep", lambda: None)
    source = (
        "<?php\n"
        "require_once 'lib.php';\n"
        "?>\n"
        "<!-- require_once 'falso.php'; -->\n"
        "<?php\n"
        "include 'outro.php';\n"
    )

    imports = astsym.extract_imports(source, "mix.php")

    assert any("lib.php" in line for line in imports)
    assert any("outro.php" in line for line in imports)
    assert not any("falso.php" in line for line in imports)
