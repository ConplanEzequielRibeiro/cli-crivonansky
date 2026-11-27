"""CLI comum dos comandos do harness (um pack por comando)."""

from __future__ import annotations

from . import packs


def _manifest(pack: str):
    return packs.manifests()[pack]


def _extract_config(argv: list[str]) -> tuple[str | None, list[str]]:
    args = list(argv)
    path = None
    if "--config" in args:
        index = args.index("--config")
        if index + 1 < len(args):
            path = args[index + 1]
            del args[index : index + 2]
    return path, args


def _forward_enabled(config_path: str | None) -> bool:
    """Compatibilidade: `/harness run <task>` encaminha para o pack dono."""
    try:
        from .config import load_config

        config = load_config(config_path)
    except Exception:  # noqa: BLE001 - sem config, mantém o comportamento antigo
        return True
    return (config.get("compat") or {}).get("forward_legacy", True) is not False


def _engine(pack, config_path=None, yes=False, dry_run=False, no_clipboard=False):
    from .engine import HarnessEngine

    return HarnessEngine(
        config_path=config_path,
        interactive=True,
        yes=yes,
        dry_run=dry_run,
        sinks=["stdout"] if no_clipboard else None,
        pack=pack,
    )


def _read_source(source: str, path: str | None) -> str:
    if source == "file":
        if not path:
            raise ValueError("informe o caminho com --file")
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    if source == "stdin":
        import sys

        return sys.stdin.read()
    import pyperclip

    return pyperclip.paste()


def _parse_run_args(args):
    task = None
    params = {}
    flags = {"yes": False, "dry_run": False, "no_clipboard": False}

    index = 0
    while index < len(args):
        item = args[index]
        if item == "--yes":
            flags["yes"] = True
        elif item == "--dry-run":
            flags["dry_run"] = True
        elif item == "--no-clipboard":
            flags["no_clipboard"] = True
        elif item == "--param":
            index += 1
            if index < len(args):
                key, _, value = args[index].partition("=")
                params[key] = value
        elif item.startswith("--"):
            key = item[2:].replace("-", "_")
            if index + 1 < len(args) and not args[index + 1].startswith("--"):
                params[key] = args[index + 1]
                index += 1
            else:
                params[key] = True
        elif task is None:
            task = item
        index += 1

    return task, params, flags


def _single(pack, config_path, task, params, yes=False, dry_run=False, no_clipboard=False):
    import yaml

    engine = _engine(pack, config_path, yes=yes, dry_run=dry_run, no_clipboard=no_clipboard)
    block = {"harness": 1, "task": task, "params": params or {}}
    raw = yaml.safe_dump(block, allow_unicode=True, sort_keys=False)
    _text, status = engine.handle_block(raw, yes_allowed=True)
    return status == "success", {"status": status}


def _exec(pack, config_path, args):
    yes = "--yes" in args
    dry_run = "--dry-run" in args
    no_clipboard = "--no-clipboard" in args

    source = "clip"
    path = None
    if "--file" in args:
        index = args.index("--file")
        if index + 1 < len(args):
            path = args[index + 1]
        source = "file"
    elif "--stdin" in args:
        source = "stdin"

    text = _read_source(source, path)
    engine = _engine(pack, config_path, yes=yes, dry_run=dry_run, no_clipboard=no_clipboard)
    results, error = engine.handle_text(text, yes_allowed=False)
    if error:
        print(f"[{pack}] {error}")
        return False, {"error": error}

    statuses = [item["status"] for item in results]
    return all(status == "success" for status in statuses), {
        "count": len(results),
        "statuses": statuses,
    }


def _tasks(pack):
    from .catalog import all_tasks, load_tasks

    load_tasks()
    count = 0
    for spec in all_tasks():
        if spec.pack not in (pack, "core"):
            continue
        marker = " [core]" if spec.pack == "core" else ""
        print(f"{spec.name:<14} [{spec.intent:<5}] {spec.description}{marker}")
        count += 1
    return True, {"count": count}


def _runs(pack, config_path, args):
    count = 10
    if "--last" in args:
        index = args.index("--last")
        if index + 1 < len(args):
            try:
                count = int(args[index + 1])
            except ValueError:
                count = 10
    engine = _engine(pack, config_path)
    records = engine.runs.last(count)
    for record in records:
        print(
            f"{record.get('id')}  {record.get('task'):<12} "
            f"{record.get('status'):<8} {record.get('duration_ms')}ms"
        )
    return True, {"count": len(records)}


def execute(pack: str, argv: list[str]) -> tuple[bool, dict]:
    """Executa um subcomando do CLI para o pack informado."""
    config_path, args = _extract_config(list(argv))
    if not args:
        print(f"[{_manifest(pack).COMMAND}] informe um subcomando (exec, run, tasks, runs, prompt, env:check)")
        return False, {"error": "subcomando ausente"}

    sub, rest = args[0], args[1:]

    if pack not in ("harness", "core"):
        from .config import load_config

        try:
            config = load_config(config_path)
        except Exception:  # noqa: BLE001 - instalação incompleta é tratada pelo subcomando
            config = None
        if config is not None and not packs.is_enabled(config, pack):
            command = _manifest(pack).COMMAND
            print(
                f"[{command}] desabilitado em harness.yaml "
                f"(plugins.{packs.config_key(pack)}.enabled=false)"
            )
            return False, {"error": "plugin desabilitado"}

    shortcuts = getattr(_manifest(pack), "SHORTCUTS", {}) or {}
    if sub in shortcuts:
        sub, rest = "run", [shortcuts[sub], *rest]

    if sub == "exec":
        return _exec(pack, config_path, rest)
    if sub == "run":
        task, params, flags = _parse_run_args(rest)
        if not task:
            print(f"[{_manifest(pack).COMMAND}] informe a tarefa")
            return False, {"error": "tarefa ausente"}
        owner = packs.owner_of(task)
        if owner and owner not in (pack, "core") and _forward_enabled(config_path):
            command = packs.pack_command(owner)
            print(f"[deprecado] `{task}` pertence a /{command}; encaminhando.")
            forwarded = (["--config", config_path] if config_path else []) + ["run", *rest]
            return execute(owner, forwarded)
        return _single(
            pack,
            config_path,
            task,
            params,
            yes=flags["yes"],
            dry_run=flags["dry_run"],
            no_clipboard=flags["no_clipboard"],
        )
    if sub == "tasks":
        return _tasks(pack)
    if sub == "runs":
        return _runs(pack, config_path, rest)
    if sub == "prompt":
        if pack == "harness":
            return _single(pack, config_path, "prompt", {})
        from .prompting import render

        text = render(pack)
        try:
            import pyperclip

            pyperclip.copy(text)
        except Exception:  # noqa: BLE001
            pass
        print(text)
        return True, {"pack": pack}
    if sub == "env:check":
        return _single(pack, config_path, "env:check", {})

    print(f"[{_manifest(pack).COMMAND}] subcomando desconhecido: {sub}")
    return False, {"error": "subcomando desconhecido"}
