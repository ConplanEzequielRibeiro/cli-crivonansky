"""Benchmark sintético do mapeamento (X.2).

Gera N arquivos PHP com SQL em um diretório temporário e mede:
code:skeleton, db:links, code:brief e knowledge:verify.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commands.complements.harness import briefing, manifest  # noqa: E402
from commands.complements.harness.task_types import TaskContext  # noqa: E402
from commands.complements.harness.tasks import links, skeleton  # noqa: E402


def generate(root: str, files: int) -> None:
    for index in range(files):
        folder = os.path.join(root, f"mod{index % 20:02d}")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"tela{index:05d}.php")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("<?php\n")
            fh.write(f"function f{index}() {{\n")
            fh.write(
                f'  return "SELECT id, nome FROM tb_t{index % 50:02d} '
                f'WHERE st = 1 AND id = {index}";\n'
            )
            fh.write("}\n")


def run(files: int = 2000, write: bool = True) -> dict:
    root = tempfile.mkdtemp(prefix="harness-bench-")
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    generate(repo, files)
    ctx = TaskContext(
        config={"legacy": {"repo_path": repo}},
        workspace=os.path.join(root, "ws"),
        run_dir=os.path.join(root, "run"),
    )

    t0 = time.perf_counter()
    skeleton_result = skeleton.handle(ctx, {})
    t1 = time.perf_counter()
    links_result = links.handle(ctx, {})
    t2 = time.perf_counter()
    packet = briefing.build(ctx, {"table": "tb_00"})
    t3 = time.perf_counter()
    verify = manifest.verify(ctx)
    t4 = time.perf_counter()

    data = {
        "files": files,
        "skeleton_ok": skeleton_result.success,
        "links_ok": links_result.success,
        "skeleton_ms": round((t1 - t0) * 1000),
        "links_ms": round((t2 - t1) * 1000),
        "brief_ms": round((t3 - t2) * 1000),
        "verify_ms": round((t4 - t3) * 1000),
        "brief_tokens": (packet.get("budget") or {}).get("estimated"),
        "freshness": verify.get("status"),
        "root": root,
    }
    if write:
        folder = os.path.join(ctx.workspace, "runs", "benchmarks")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"bench-{time.strftime('%Y%m%d-%H%M%S')}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        data["report"] = path
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=2000)
    args = parser.parse_args(argv)
    data = run(args.files)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data["skeleton_ok"] and data["links_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
