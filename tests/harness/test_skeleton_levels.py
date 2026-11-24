"""code:skeleton em níveis: índice, MAP.md, fatias por diretório e exclude (T08–T11)."""

from commands.complements.harness import filters
from commands.complements.harness.task_types import TaskContext
from commands.complements.harness.tasks import skeleton


def _ctx(tmp_path, legacy=None):
    return TaskContext(
        config={"legacy": {"repo_path": str(tmp_path / "repo"), **(legacy or {})}},
        workspace=str(tmp_path / "ws"),
        run_dir=str(tmp_path / "run"),
    )


def _big_repo(tmp_path, dirs=30, files=12):
    repo = tmp_path / "repo"
    for d in range(dirs):
        folder = repo / f"modulo{d:02d}"
        folder.mkdir(parents=True)
        for f in range(files):
            body = "".join(
                f"function fn_{d}_{f}_{s}() {{ return 1; }}\n" for s in range(8)
            )
            if f == 0:
                body += 'mysql_query("SELECT * FROM tb_central WHERE 1");\n'
            (folder / f"arq{f:02d}.php").write_text("<?php\n" + body, encoding="utf-8")
    return repo


def _out(tmp_path, name):
    return (tmp_path / "ws" / "knowledge" / "skeleton" / name).read_text(encoding="utf-8")


def test_large_repo_index_fits_budget_without_cutting_mid_list(tmp_path):
    _big_repo(tmp_path)

    result = skeleton.handle(_ctx(tmp_path), {})

    assert result.success
    text = _out(tmp_path, "SKELETON.md")
    assert len(text) <= skeleton.SKELETON_BUDGET
    assert "[truncado" not in text
    assert "`tb_central`" in text
    assert "level=dir" in text
    # os símbolos não vão para o índice: ficam nas fatias
    assert "fn_0_0_0" not in text
    assert "fn_0_0_0" in _out(tmp_path, "dirs/modulo00.md")


def test_map_lists_top_files_per_directory(tmp_path):
    _big_repo(tmp_path, dirs=2, files=10)

    skeleton.handle(_ctx(tmp_path), {})

    mapa = _out(tmp_path, "MAP.md")
    assert "## modulo00/ (10)" in mapa
    # arq00 cita tabela → ranqueado primeiro
    first = mapa.split("## modulo00/ (10)")[1].split("\n")[2]
    assert "arq00.php" in first
    assert "tab: tb_central" in first
    assert "+5 arquivo(s)" in mapa


def test_level_dir_returns_slice_with_symbols(tmp_path):
    _big_repo(tmp_path, dirs=3, files=2)

    result = skeleton.handle(_ctx(tmp_path), {"level": "dir", "path": "modulo01"})

    assert result.success
    assert "fn_1_0_0" in result.details
    assert "fn_0_0_0" not in result.details


def test_level_dir_requires_path_and_known_dir(tmp_path):
    _big_repo(tmp_path, dirs=1, files=1)

    assert skeleton.handle(_ctx(tmp_path), {"level": "dir"}).exit_code == 2
    assert not skeleton.handle(_ctx(tmp_path), {"level": "dir", "path": "nao_existe"}).success
    assert not skeleton.handle(_ctx(tmp_path), {"level": "xyz"}).success


def test_level_map_returns_map_text(tmp_path):
    _big_repo(tmp_path, dirs=2, files=2)

    result = skeleton.handle(_ctx(tmp_path), {"level": "map"})

    assert result.success
    assert "# Mapa do código" in result.details


def test_exclude_param_and_config_prune_tree(tmp_path):
    _big_repo(tmp_path, dirs=3, files=1)

    result = skeleton.handle(
        _ctx(tmp_path, {"exclude": ["modulo00"]}), {"exclude": "modulo01,*.bak.php"}
    )

    assert result.success
    data = __import__("json").loads(_out(tmp_path, "project.json"))
    assert set(data["dirs"]) == {"modulo02"}
    assert data["exclude"] == ["modulo00", "modulo01", "*.bak.php"]


def test_stale_slices_are_removed(tmp_path):
    repo = _big_repo(tmp_path, dirs=2, files=1)
    skeleton.handle(_ctx(tmp_path), {})
    assert (tmp_path / "ws/knowledge/skeleton/dirs/modulo01.md").exists()

    for item in (repo / "modulo01").iterdir():
        item.unlink()
    skeleton.handle(_ctx(tmp_path), {"full": True})

    assert not (tmp_path / "ws/knowledge/skeleton/dirs/modulo01.md").exists()


def test_is_excluded_patterns():
    assert filters.is_excluded("legado/a.php", ["legado"])
    assert filters.is_excluded("x/y/z.bak.php", ["*.bak.php"])
    assert filters.is_excluded("rel/2020/a.php", ["rel/*"])
    assert not filters.is_excluded("relatorios/a.php", ["rel"])
