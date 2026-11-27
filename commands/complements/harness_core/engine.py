"""Motor de execução do harness."""

import json
import time
import traceback

from .catalog import get_task, load_tasks
from .config import get_output, get_workspace, load_config
from .contract import ContractError, extract_blocks, new_id, parse_block
from . import redact
from .formatter import format_result, mask_secrets
from .policy import check_policy
from .runs import RunStore
from .sinks import emit
from .task_types import TaskContext

# Confirmação de tarefas de escrita: o host (TUI) pode substituir o ``input()``
# por uma caixa de diálogo. ``None`` mantém o comportamento de terminal.
_CONFIRM_HANDLER = None


def set_confirm_handler(handler) -> None:
    """``handler(task, params, preview) -> bool`` ou ``None`` para o padrão."""
    global _CONFIRM_HANDLER
    _CONFIRM_HANDLER = handler


def get_confirm_handler():
    return _CONFIRM_HANDLER


def _error_details(exc: Exception) -> str:
    """Detalhes de uma exceção inesperada, com o caminho quando for OSError."""
    lines = [f"{type(exc).__name__}: {exc}"]
    filename = getattr(exc, "filename", None)
    if filename:
        lines.append(f"caminho: {filename}")
    winerror = getattr(exc, "winerror", None)
    if winerror:
        lines.append(f"winerror: {winerror}")

    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    lines.extend(["", trace[-3000:]])
    return "\n".join(lines)


class HarnessEngine:
    def __init__(
        self,
        config_path: str | None = None,
        interactive: bool = True,
        yes: bool = False,
        dry_run: bool = False,
        sinks: list[str] | None = None,
        config: dict | None = None,
        pack: str | None = None,
    ):
        self.config = config if config is not None else load_config(config_path)
        self.workspace = get_workspace(self.config)
        self.output = get_output(self.config)
        self.pack = pack
        self.interactive = interactive
        self.yes = yes
        self.dry_run = dry_run
        self.sinks = sinks or self.output.get("default_sinks", ["stdout"])
        self.runs = RunStore(self.workspace)
        self.max_chars = int((self.output.get("max_chars") or {}).get("clipboard", 12000))
        load_tasks()

    # ------------------------------------------------------------------
    def handle_text(
        self, text: str, yes_allowed: bool = False, origin: str | None = None
    ) -> tuple[list[dict], str | None]:
        blocks = extract_blocks(text)
        if not blocks:
            return [], "nenhum bloco ```crivonansky encontrado"

        limit = int(self.output.get("max_blocks_per_message") or 5)
        if limit > 0:
            blocks = blocks[:limit]

        results = []
        for raw in blocks:
            result_text, status = self.handle_block(
                raw, yes_allowed=yes_allowed, origin=origin
            )
            results.append({"text": result_text, "status": status})

            if status in ("failure", "error", "denied", "timeout"):
                try:
                    block = parse_block(raw)
                    if block.continue_on_failure:
                        continue
                except ContractError:
                    pass
                break

        return results, None

    # ------------------------------------------------------------------
    def handle_block(
        self, raw: str, yes_allowed: bool = False, origin: str | None = None
    ) -> tuple[str, str]:
        start = time.time()
        origin = origin or ("user" if yes_allowed else "llm")
        generated_id = new_id()

        try:
            block = parse_block(raw, generated_id=generated_id)
        except ContractError as exc:
            return self._finish(
                generated_id, "unknown", "error", 2, start, str(exc), str(exc), [], raw
            )

        spec = get_task(block.task)
        if spec is None:
            return self._finish(
                block.id,
                block.task,
                "denied",
                3,
                start,
                f"tarefa desconhecida: {block.task}",
                "",
                [],
                raw,
            )

        if self.pack and spec.pack not in (self.pack, "core"):
            from .packs import pack_command

            command = pack_command(spec.pack) or spec.pack
            return self._finish(
                block.id,
                block.task,
                "denied",
                3,
                start,
                f"tarefa `{block.task}` pertence ao plugin /{command}",
                f"Use `/{command} run {block.task} ...`.",
                [],
                raw,
            )

        if origin == "llm" and self.pack:
            from .packs import manifests

            allowed = set((self.config.get("policy") or {}).get("llm_allowed_tasks") or [])
            denied = set(getattr(manifests()[self.pack], "DEFAULT_LLM_DENIED", ()) or ())
            if block.task in denied and block.task not in allowed:
                return self._finish(
                    block.id,
                    block.task,
                    "denied",
                    3,
                    start,
                    f"negado: `{block.task}` não pode ser pedida por bloco do LLM",
                    "",
                    [],
                    raw,
                )

        missing = [name for name in spec.required if name not in block.params]
        if missing:
            return self._finish(
                block.id,
                block.task,
                "error",
                2,
                start,
                f"parâmetros obrigatórios ausentes: {', '.join(missing)}",
                "",
                [],
                raw,
            )

        allowed = set(spec.required) | set(spec.optional)
        unknown = sorted(set(block.params) - allowed)
        if unknown:
            return self._finish(
                block.id,
                block.task,
                "error",
                2,
                start,
                f"parâmetros desconhecidos: {', '.join(unknown)}",
                "",
                [],
                raw,
            )

        decision, reason = check_policy(
            block, spec, self.config, self.interactive, yes_allowed, self.yes, origin
        )
        if decision == "deny":
            return self._finish(
                block.id, block.task, "denied", 3, start, f"negado: {reason}", "", [], raw
            )

        ctx = TaskContext(
            config=self.config,
            workspace=self.workspace,
            run_dir=self.runs.run_dir(block.id),
            interactive=self.interactive,
            yes=self.yes,
            dry_run=self.dry_run,
            origin=origin,
        )

        if decision == "confirm":
            preview = self._preview(spec, ctx, block)
            if not self._confirm(block, preview):
                return self._finish(
                    block.id, block.task, "denied", 3, start, "recusado pelo usuário", "", [], raw
                )

        if self.dry_run:
            return self._finish(
                block.id, block.task, "success", 0, start, "dry-run: não executado", "", [], raw
            )

        try:
            result = spec.handler(ctx, block.params)
        except PermissionError as exc:
            return self._finish(block.id, block.task, "denied", 3, start, str(exc), "", [], raw)
        except Exception as exc:  # noqa: BLE001
            return self._finish(
                block.id,
                block.task,
                "error",
                1,
                start,
                f"erro ao executar: {exc}",
                _error_details(exc),
                [],
                raw,
            )

        status = result.status or ("success" if result.success else "failure")
        return self._finish(
            block.id,
            block.task,
            status,
            result.exit_code,
            start,
            result.summary,
            result.details,
            result.artifacts,
            raw,
            result.hint,
        )

    # ------------------------------------------------------------------
    def _preview(self, spec, ctx, block) -> str | None:
        """Texto exibido antes da confirmação (ex.: diff da ficha a gravar)."""
        if spec.preview_fn is None:
            return None
        try:
            return spec.preview_fn(ctx, block.params)
        except Exception as exc:  # noqa: BLE001 - a prévia nunca impede a tarefa
            return f"(prévia indisponível: {exc})"

    def _confirm(self, block, preview: str | None = None) -> bool:
        handler = get_confirm_handler()
        if handler is not None:
            try:
                return bool(handler(block.task, dict(block.params), preview))
            except Exception:  # noqa: BLE001 - host indisponível não autoriza
                return False

        print(f"\n[harness] tarefa de escrita: {block.task}")
        print(json.dumps(block.params, ensure_ascii=False, indent=2))
        if preview:
            print(preview)
        try:
            answer = input("Executar? [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in ("y", "yes", "s", "sim")

    def _finish(
        self,
        block_id: str,
        task: str,
        status: str,
        exit_code: int,
        start: float,
        summary: str,
        details: str,
        artifacts: list[str],
        raw: str,
        hint: str = "",
    ) -> tuple[str, str]:
        duration = int((time.time() - start) * 1000)
        summary = mask_secrets(summary, self.config)
        details = mask_secrets(details, self.config)
        raw_details = details

        policy = redact.get_policy(self.config)
        if redact.applies(policy, "exec") or (
            task == "context:pack" and redact.applies(policy, "context:pack")
        ):
            stats: dict = {}
            details, stats = redact.redact_text(details, policy, stats)
            summary, stats = redact.redact_text(summary, policy, stats)
            if stats:
                summary = f"{summary} [redact: {redact.format_stats(stats)}]"
        full_log = raw_details if policy.keep_raw_log else details

        text, _truncated = format_result(
            block_id,
            task,
            status,
            exit_code,
            duration,
            summary,
            details,
            artifacts,
            self.max_chars,
            hint,
        )

        try:
            self.runs.write(block_id, raw, text, full_log)
            self.runs.append_index(
                {
                    "id": block_id,
                    "task": task,
                    "status": status,
                    "duration_ms": duration,
                    "approved_by": "none" if status == "denied" else "auto",
                    "sinks": self.sinks,
                }
            )
        except OSError:
            pass

        emit(text, self.sinks)
        return text, status
