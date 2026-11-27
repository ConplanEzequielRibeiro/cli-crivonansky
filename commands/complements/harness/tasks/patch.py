"""Tarefa patch:apply — aplica um diff unificado preservando o formato dos arquivos.

O diff do chat é UTF-8/LF; o legado costuma ser ISO-8859-1/CRLF. Antes do
``git apply`` cada linha é reescrita no encoding, EOL e BOM do arquivo alvo
(``patching.py``); depois o resultado é conferido e revertido se o formato mudou.
Também exige uma branch de trabalho e uma árvore limpa nos arquivos tocados.
"""

import os

from .. import patching
from commands.complements.harness_core.catalog import get_task, register
from commands.complements.harness_core.runner import run_process
from commands.complements.harness_core.task_types import TaskResult, TaskSpec
from commands.complements.harness_core.util import as_bool, as_int, ensure_dir, legacy_repo
from ..encoding import source_encoding

DEFAULT_PROTECTED = ["main", "master", "develop", "production", "producao"]


def _git(repo: str, *args: str, timeout: float = 60):
    return run_process(["git", *args], cwd=repo, timeout=timeout)


def _patch_config(ctx) -> dict:
    return (getattr(ctx, "config", None) or {}).get("patch") or {}


def _current_branch(repo: str) -> str:
    result = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return result.combined.strip() if result.exit_code == 0 else ""


def _dirty_targets(repo: str, targets: list[str]) -> list[str]:
    if not targets:
        return []
    result = _git(repo, "status", "--porcelain", "--", *targets)
    if result.exit_code != 0:
        return []
    return [line[3:].strip() for line in result.combined.splitlines() if line.strip()]


def _switch_branch(repo: str, branch: str) -> str | None:
    """Cria (ou troca para) ``branch``; devolve a mensagem de erro, se houver."""
    exists = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    args = ["checkout", branch] if exists.exit_code == 0 else ["checkout", "-b", branch]
    result = _git(repo, *args)
    return None if result.exit_code == 0 else result.combined.strip()


def _inside(repo: str, rel: str) -> bool:
    full = os.path.realpath(os.path.join(repo, rel))
    root = os.path.realpath(repo)
    return full == root or full.startswith(root + os.sep)


def handle(ctx, params):
    diff = params.get("diff")
    if not diff:
        return TaskResult(False, "parâmetro 'diff' obrigatório", exit_code=2)

    repo = legacy_repo(ctx)
    config = _patch_config(ctx)
    encoding = source_encoding(ctx)

    try:
        files = patching.parse_diff(str(diff))
    except patching.PatchFormatError as exc:
        return TaskResult(False, f"diff inválido: {exc}", exit_code=2)
    if not files:
        return TaskResult(False, "nenhum arquivo reconhecido no diff", exit_code=2)
    if any(item.binary for item in files):
        return TaskResult(False, "diff binário não é suportado", exit_code=2)

    strip = as_int(params.get("strip"), -1)
    if strip < 0:
        strip = patching.detect_strip(files)

    formats: dict[str, patching.FileFormat] = {}
    targets: list[str] = []
    for item in files:
        target = item.target(strip)
        if not target:
            return TaskResult(False, "caminho de arquivo ausente no diff", exit_code=2)
        if not _inside(repo, target) or os.path.isabs(target):
            return TaskResult(
                False, f"caminho fora do repositório: {target}", exit_code=2
            )
        targets.append(target)
        full = os.path.join(repo, target)
        if item.is_new:
            formats[target] = patching.guess_new_file_format(
                repo, target, encoding, str(config.get("new_file_eol", "auto"))
            )
        elif os.path.isfile(full):
            with open(full, "rb") as fh:
                formats[target] = patching.detect_format(fh.read(), encoding)
        else:
            return TaskResult(False, f"arquivo alvo não existe: {target}", exit_code=2)

    # --- branch e árvore ---------------------------------------------------
    protected = config.get("protected_branches") or DEFAULT_PROTECTED
    branch = str(params.get("branch") or "").strip()
    current = _current_branch(repo)
    notes: list[str] = []

    if not branch and current in protected:
        return TaskResult(
            False,
            f"branch protegida ({current}): informe `branch` para trabalhar em outra",
            hint="Ex.: branch=ajuste-cadastro — a branch é criada a partir da atual.",
            exit_code=3,
        )

    dirty = _dirty_targets(repo, targets)
    if dirty and not as_bool(params.get("allow_dirty"), as_bool(config.get("allow_dirty"))):
        return TaskResult(
            False,
            "há alterações não commitadas nos arquivos do patch",
            details="\n".join(dirty),
            hint="Faça commit/stash ou use allow_dirty=true.",
            exit_code=3,
        )

    # --- conversão ----------------------------------------------------------
    try:
        converted = patching.convert_diff(str(diff), formats, strip)
    except patching.PatchFormatError as exc:
        return TaskResult(False, f"não foi possível converter o diff: {exc}", exit_code=2)

    ensure_dir(ctx.run_dir)
    patch_path = os.path.join(ctx.run_dir, "patch.diff")
    with open(patch_path, "wb") as fh:
        fh.write(converted)

    apply_args = ["apply", f"-p{strip}", "--whitespace=nowarn"]
    check = _git(repo, *apply_args, "--check", patch_path)
    if check.exit_code != 0 or check.timed_out:
        return TaskResult(
            False,
            "o diff não se aplica limpo",
            details=check.combined,
            hint="O contexto do diff não bate com o arquivo atual; peça um diff novo.",
            exit_code=check.exit_code or 1,
        )

    if branch and branch != current:
        error = _switch_branch(repo, branch)
        if error:
            return TaskResult(False, f"não foi possível usar a branch {branch}", details=error, exit_code=1)
        notes.append(f"branch: {branch}")
    elif current:
        notes.append(f"branch: {current}")

    snapshots: dict[str, bytes] = {}
    for target in targets:
        full = os.path.join(repo, target)
        if os.path.isfile(full):
            with open(full, "rb") as fh:
                snapshots[target] = fh.read()

    applied = _git(repo, *apply_args, patch_path)
    if applied.exit_code != 0 or applied.timed_out:
        return TaskResult(
            False,
            "falha ao aplicar o diff",
            details=applied.combined,
            exit_code=applied.exit_code or 1,
        )

    # --- conferência do formato --------------------------------------------
    problems: list[str] = []
    for item in files:
        target = item.target(strip)
        full = os.path.join(repo, target)
        if item.is_delete or not os.path.isfile(full):
            continue
        with open(full, "rb") as fh:
            after = fh.read()
        for problem in patching.verify_result(formats[target], after):
            problems.append(f"{target}: {problem}")

    if problems:
        _git(repo, *apply_args, "-R", patch_path)
        return TaskResult(
            False,
            "patch revertido: o formato dos arquivos mudou",
            details="\n".join(problems),
            exit_code=1,
        )

    for target in targets:
        notes.append(f"{target}: {formats[target].describe()}")

    details = ["diff aplicado com sucesso", *notes]
    ok = True

    if as_bool(params.get("verify")):
        spec = get_task("verify")
        if spec is None:
            details.append("pipeline 'verify' não encontrada")
            ok = False
        else:
            result = spec.handler(ctx, {})
            details.append(f"[verify] {result.summary}")
            if result.details:
                details.append(result.details)
            ok = result.success

    return TaskResult(
        success=ok,
        summary="patch aplicado" + (" e verificado" if as_bool(params.get("verify")) else ""),
        details="\n".join(details),
        exit_code=0 if ok else 1,
    )


register(
    TaskSpec(
        name="patch:apply", pack="harness_patch",
        intent="write",
        description=(
            "Aplica um diff unificado preservando encoding/CRLF/BOM do arquivo; "
            "exige branch não protegida e árvore limpa nos alvos"
        ),
        required=["diff"],
        optional=["verify", "branch", "allow_dirty", "strip"],
        handler=handle,
    )
)
