"""Tarefa env:check."""

import os
import urllib.request

from commands.complements.harness_core.catalog import register
from commands.complements.harness_core.config import get_legacy, get_tool, get_tool_path
from ..filters import iter_files
from ..profiles import resolve_profile
from commands.complements.harness_core.runner import run_process
from commands.complements.harness_core.task_types import TaskResult, TaskSpec
from commands.complements.harness_core.util import legacy_repo, looks_like_path
from .rag import tools_problem

FILE_COUNT_CAP = 20000


def _http_ok(url: str, timeout: float = 3) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200, resp.read().decode("utf-8", "replace")[:300]
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _line(label: str, ok: bool, detail: str = "") -> str:
    mark = "OK   " if ok else "FALHA"
    suffix = f" - {detail}" if detail else ""
    return f"- [{mark}] {label}{suffix}"


def _dir_size(path: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total


def _mb(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _check_command(label: str, cmd: list[str], timeout: float = 15) -> tuple[str, bool]:
    """Roda um comando externo sem derrubar o env:check quando ele não existe."""
    try:
        res = run_process(cmd, timeout=timeout)
    except (OSError, ValueError) as exc:
        return _line(label, False, f"não foi possível executar: {exc}"), False

    if res.timed_out:
        return _line(label, False, "timeout"), False

    ok = res.exit_code == 0
    detail = (res.combined.splitlines() or [""])[0]
    if not ok:
        lines = [line.strip() for line in res.combined.splitlines() if line.strip()]
        detail = lines[-1] if lines else f"exit code {res.exit_code}"
    return _line(label, ok, detail), ok


def handle(ctx, params):
    lines: list[str] = []
    ok_all = True

    def add(line: str, ok: bool) -> None:
        nonlocal ok_all
        lines.append(line)
        ok_all = ok_all and ok

    add(*_check_command("git", ["git", "--version"], timeout=10))

    docker_line, docker_ok = _check_command("docker", ["docker", "info"], timeout=15)
    if docker_ok:
        add(docker_line, True)
    else:
        # O core (esqueleto, busca, db:links, docs) funciona sem Docker.
        lines.append(
            "- AVISO: docker - indisponível (fixture/db ao vivo desativados)"
        )

    workspace_path = os.path.abspath(ctx.workspace)
    try:
        os.makedirs(workspace_path, exist_ok=True)
        probe = os.path.join(workspace_path, f".env-check-{os.getpid()}.tmp")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
        add(_line("workspace", True, workspace_path), True)
    except OSError as exc:
        add(_line("workspace", False, f"{workspace_path}: {exc}"), False)

    knowledge_size = _dir_size(os.path.join(workspace_path, "knowledge"))
    runs_size = _dir_size(os.path.join(workspace_path, "runs"))
    lines.append(
        f"- tamanho do workspace: knowledge {_mb(knowledge_size)} | runs {_mb(runs_size)} "
        "(limpe com `clean:artifacts`/`clean:runs`)"
    )

    plugin_python = get_tool_path(ctx.config, "python")
    if plugin_python and looks_like_path(plugin_python):
        exists = os.path.isfile(plugin_python)
        add(
            _line(
                "python do plugin",
                exists,
                plugin_python if exists else f"não encontrado: {plugin_python}",
            ),
            exists,
        )

    codeknow = get_tool_path(ctx.config, "codeknow")
    if codeknow:
        lines.append("- AVISO: tools.codeknow ainda configurado, mas não é mais usado")

    try:
        profile = resolve_profile(ctx.config)
    except ValueError as exc:
        add(_line("perfil", False, str(exc)), False)
    else:
        add(
            _line(
                "perfil",
                True,
                f"{profile.name} ({profile.label}) | dialeto {profile.db_dialect} "
                f"| encoding {profile.encoding}",
            ),
            True,
        )

        repo_config = get_legacy(ctx.config, "repo_path")
        if repo_config:
            repo = legacy_repo(ctx)
            if not os.path.isdir(repo):
                add(_line("repositório", False, repo), False)
            else:
                count = 0
                for _ in iter_files(repo, profile.code_extensions):
                    count += 1
                    if count >= FILE_COUNT_CAP:
                        break
                if count:
                    suffix = " (contagem limitada)" if count >= FILE_COUNT_CAP else ""
                    add(
                        _line(
                            "arquivos do perfil",
                            True,
                            f"{count} arquivo(s) {sorted(profile.code_extensions)}{suffix}",
                        ),
                        True,
                    )
                else:
                    lines.append(
                        "- AVISO: nenhum arquivo com as extensões do perfil "
                        f"({', '.join(sorted(profile.code_extensions))}); "
                        "confira legacy.stack/extensions"
                    )
        else:
            lines.append("- AVISO: legacy.repo_path não configurado")

    rag_path = get_tool_path(ctx.config, "rag", "path")
    if rag_path:
        problem = tools_problem(ctx.config)
        add(
            _line("rag (tools.rag)", problem is None, problem or "path/python/main.py ok"),
            problem is None,
        )

        rag_api = get_tool(ctx.config, "rag", "api")
        if rag_api:
            ok, detail = _http_ok(rag_api.rstrip("/") + "/health")
            if ok:
                add(_line("rag (api)", True, detail), True)
            else:
                # API parada não invalida o ambiente: o RAG é opcional.
                lines.append(
                    f"- AVISO: rag (api) - parada; suba com `/harness start --rag`"
                )
    else:
        lines.append("- AVISO: RAG não configurado (opcional; o código usa busca JIT)")

    summary = "ambiente OK" if ok_all else "há verificações com falha"
    return TaskResult(
        success=ok_all,
        summary=summary,
        details="\n".join(lines),
        exit_code=0 if ok_all else 1,
    )


register(
    TaskSpec(
        name="env:check", pack="core",
        intent="read",
        description="Verifica o ambiente do harness (git, docker, workspace, perfil e RAG opcional)",
        required=[],
        optional=[],
        handler=handle,
    )
)
