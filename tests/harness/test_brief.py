"""code:brief: âncoras, impacto, budget e omissões (M2)."""

import json

from commands.complements.harness import briefing
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import brief, links, skeleton


def _ctx(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cadastro").mkdir(parents=True)
    (repo / "cadastro" / "a.php").write_text(
        "<?php\nfunction salvar() {\n"
        '  return "UPDATE tb_veiculos SET st=2 WHERE id=1";\n}\n',
        encoding="utf-8",
    )
    (repo / "cadastro" / "b.php").write_text(
        "<?php\nfunction listar() {\n"
        '  return "SELECT * FROM tb_veiculos";\n}\n',
        encoding="utf-8",
    )
    ctx = TaskContext(
        config={"legacy": {"repo_path": str(repo)}, "pipelines": {"verify": []}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )
    assert skeleton.handle(ctx, {}).success
    assert links.handle(ctx, {}).success
    return ctx


def test_brief_table_anchor(tmp_path):
    ctx = _ctx(tmp_path)

    packet = briefing.build(ctx, {"table": "tb_veiculos"})

    assert packet["schema"] == "harness.brief.v1"
    assert packet["anchor"]["type"] == "table"
    paths = [item["path"] for item in packet["read_first"]]
    assert "cadastro/a.php" in paths
    assert "cadastro/b.php" in paths
    assert packet["impact"]["tables"][0]["name"] == "tb_veiculos"
    assert packet["impact"]["tables"][0]["writes"] >= 1
    assert packet["validation"] == ["verify"]


def test_brief_path_and_symbol_anchors(tmp_path):
    ctx = _ctx(tmp_path)

    by_path = briefing.build(ctx, {"path": "cadastro/a.php"})
    by_symbol = briefing.build(ctx, {"symbol": "salvar"})

    assert by_path["anchor"]["resolved"] == ["cadastro/a.php"]
    assert by_path["read_first"][0]["path"] == "cadastro/a.php"
    assert by_symbol["anchor"]["type"] == "symbol"
    assert by_symbol["read_first"][0]["path"] == "cadastro/a.php"


def test_brief_budget_and_omissions(tmp_path):
    ctx = _ctx(tmp_path)

    packet = briefing.build(ctx, {"table": "tb_veiculos", "max_paths": 1, "budget": 500})

    assert len(packet["read_first"]) <= 1
    assert packet["omissions"]


def test_brief_requires_anchor(tmp_path):
    ctx = _ctx(tmp_path)

    packet = briefing.build(ctx, {})

    assert "error" in packet


def test_brief_task_json(tmp_path):
    ctx = _ctx(tmp_path)

    result = brief.handle(ctx, {"table": "tb_veiculos", "json": True})

    assert result.success
    packet = json.loads(result.details.split("\n\n[redact:")[0])
    assert packet["anchor"]["value"] == "tb_veiculos"
    assert "read_first" in packet


def test_brief_render_mentions_source_check(tmp_path):
    ctx = _ctx(tmp_path)

    packet = briefing.build(ctx, {"table": "tb_veiculos"})
    text = briefing.render(packet)

    assert "# Brief: table `tb_veiculos`" in text
    assert "Ler primeiro" in text
    assert "Confirme no código" in text
