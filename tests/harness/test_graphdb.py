"""Store SQLite: sync, cache, impacto e integração (M1)."""

from types import SimpleNamespace

from commands.complements.harness import graphdb
from commands.complements.harness_core.task_types import TaskContext
from commands.complements.harness.tasks import graph as graph_task
from commands.complements.harness.tasks import links, skeleton


def _ctx(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cadastro").mkdir(parents=True)
    (repo / "cadastro" / "a.php").write_text(
        "<?php\ninclude '../includes/x.php';\nfunction salvar() {\n"
        '  return "UPDATE tb_veiculos SET st=2";\n}\n',
        encoding="utf-8",
    )
    return TaskContext(
        config={"legacy": {"repo_path": str(repo)}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    ), repo


def _profile():
    return SimpleNamespace(languages={".php": "php"}, code_extensions={".php"})


def _index(repo):
    path = repo / "cadastro" / "a.php"
    stat = path.stat()
    return {
        "cadastro/a.php": {
            "loc": 6,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "symbols": [{"name": "salvar", "kind": "function", "line": 3}],
            "imports": ["../includes/x.php"],
        }
    }


def _links():
    return (
        [
            {
                "table": "tb_veiculos",
                "file": "cadastro/a.php",
                "line": 4,
                "operation": "write",
                "symbol": "salvar",
                "confidence": "parsed",
                "snippet": "UPDATE tb_veiculos SET st=2",
            }
        ],
        [
            {
                "table": "tb_veiculos",
                "columns": ["id_cat"],
                "ref_table": "tb_categorias",
                "ref_columns": ["id_cat"],
                "evidence": ["cadastro/a.php:4"],
            }
        ],
        [
            {
                "file": "cadastro/a.php",
                "line": 2,
                "type": "include",
                "target": "../includes/x.php",
            }
        ],
    )


def test_sync_skeleton_and_cache(tmp_path):
    ctx, repo = _ctx(tmp_path)
    index = _index(repo)

    first = graphdb.sync_skeleton(ctx, index, _profile(), 3)
    second = graphdb.sync_skeleton(ctx, index, _profile(), 3)

    assert first["files"] == 1
    assert second["files"] == 1
    counts = graphdb.stats(ctx)
    assert counts["files"] == 1
    assert counts["symbols"] == 1
    assert counts["imports"] == 1


def test_sync_links_and_impact_queries(tmp_path):
    ctx, repo = _ctx(tmp_path)
    graphdb.sync_skeleton(ctx, _index(repo), _profile(), 3)
    graphdb.sync_links(ctx, *_links())

    counts = graphdb.stats(ctx)
    assert counts["tables"] == 2
    assert counts["table_ops"] == 1
    assert counts["fk_inferred"] == 1
    assert counts["includes"] == 1

    ops = graphdb.impact_by_table(ctx, "tb_veiculos")
    assert ops[0]["access"] == "write"
    assert ops[0]["symbol"] == "salvar"
    assert graphdb.impact_by_symbol(ctx, "salvar")[0]["table_name"] == "tb_veiculos"

    files = graphdb.files_by_surface(ctx, "cadastro")
    assert files[0]["path"] == "cadastro/a.php"


def test_custom_graph_path(tmp_path):
    ctx, _repo = _ctx(tmp_path)
    custom = tmp_path / "custom.sqlite"
    ctx.config["graph"] = {"path": str(custom)}

    assert graphdb.db_path(ctx) == str(custom)


def test_skeleton_and_links_feed_store(tmp_path):
    ctx, repo = _ctx(tmp_path)
    ctx.config["legacy"]["encoding"] = "utf-8"

    assert skeleton.handle(ctx, {}).success
    assert links.handle(ctx, {}).success

    counts = graphdb.stats(ctx)
    assert counts["files"] >= 1
    assert counts["table_ops"] >= 1


def test_force_and_graph_tasks(tmp_path):
    ctx, repo = _ctx(tmp_path)
    index = _index(repo)

    graphdb.sync_skeleton(ctx, index, _profile(), 3)
    graphdb.sync_skeleton(ctx, index, _profile(), 3, force=True)

    stats = graph_task.handle_stats(ctx, {"json": True})
    assert stats.success
    assert "files" in stats.details

    out = tmp_path / "graph.jsonl"
    export = graph_task.handle_export(ctx, {"format": "jsonl", "out": str(out)})
    assert export.success
    assert out.is_file()
    assert out.read_text(encoding="utf-8").strip()
