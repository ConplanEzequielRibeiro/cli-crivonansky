"""Marcadores de truncamento explícitos, em fronteira de linha (T07)."""

from commands.complements.harness import formatter


def test_marker_shape_and_hint():
    marker = formatter.truncation_marker(3, hint="Use path menor.")

    assert marker.startswith("[truncado: 3 linha(s) omitida(s)")
    assert "Use path menor." in marker


def test_cut_head_cuts_on_line_boundary():
    text = "\n".join(f"linha {i:03d}" for i in range(100))

    cut, omitted = formatter.cut_head(text, 200, hint="dica")

    assert omitted > 0
    body = cut.split("\n[truncado")[0]
    assert all(line.startswith("linha ") and len(line) == 9 for line in body.splitlines())
    assert "dica" in cut
    assert len(cut) <= 200 + 200  # marcador não explode o limite


def test_truncate_reports_flag_and_keeps_short_text():
    assert formatter.truncate("curto", 100) == ("curto", False)

    out, cut = formatter.truncate(
        "\n".join(f"registro {i:04d} " + "x" * 10 for i in range(50)), 100, hint="refine"
    )
    assert cut and "[truncado:" in out and "refine" in out


def test_single_huge_line_gets_character_marker():
    out, cut = formatter.truncate("a" * 5000, 100)

    assert cut
    assert "caractere" in out


def test_format_result_carries_hint():
    text, truncated = formatter.format_result(
        block_id="c-1", task="code:search", status="success", exit_code=0, duration_ms=1,
        summary="ok", details="\n".join(f"ocorrência {i:04d}" for i in range(200)),
        artifacts=[], max_chars=300, hint="Use `max_results` menor.",
    )

    assert truncated and "truncated: true" in text
    assert "[truncado:" in text
    assert "max_results" in text
