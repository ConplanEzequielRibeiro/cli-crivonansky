"""Executa os evals do brief na fixture/config atual (M5)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commands.complements.harness import evals  # noqa: E402
from commands.complements.harness_core.config import get_workspace, load_config  # noqa: E402
from commands.complements.harness_core.task_types import TaskContext  # noqa: E402


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    config_path = argv[0] if argv else None
    config = load_config(config_path)
    ctx = TaskContext(
        config=config,
        workspace=get_workspace(config),
        run_dir=get_workspace(config),
    )
    data, path = evals.run(ctx)
    print(evals.describe(data))
    if path:
        print(f"\nrelatório: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
