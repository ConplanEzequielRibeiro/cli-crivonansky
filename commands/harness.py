"""Comando /harness — ponto de entrada do harness de desenvolvimento assistido."""

import sys

from core.command import Command

from .complements.harness import ops


class HarnessCommand(Command):
    name = "harness"
    description = "Executa o harness de desenvolvimento assistido"
    help_text = """Uso:
  /harness install [--force] [--skip-docker] [--check-only] [--python CAMINHO] [--with-rag]
  /harness start [--rag] [--no-docker]
  /harness stop [--purge]
  /harness prepare [--full] [--sync] [--rag] [--no-docker]
  /harness preprocess [--sync] [--full] [--no-codeknow] [--no-wiki]
  /harness config
  /harness exec --clip | --file F | --stdin [--yes] [--dry-run]
  /harness run <task> [--param k=v ...] [--yes] [--dry-run]
      ex.: run code:skeleton --level map | run code:skeleton --level dir --path cadastro
           run notes:draft --module cadastro | run notes:stale
           run patch:apply --file F --branch ajuste   (preserva encoding/CRLF)
  /harness ask "<pergunta>" [--context map,notes,db,code,docs,rag,skeleton] [--budget TOKENS]
  /harness state save --clip | list | load [--last | NOME]   (retomar tarefa em outra conversa)
  /harness notes draft <dir> | save --clip | stale
  /harness watch clip [--stop] | watch downloads [--path P] [--stop]
  /harness kb export [--out P] [--max_chars N]
  /harness clean artifacts [--scope skeleton,db,links,docs,legacy-code] [--param dry_run=true]
  /harness clean runs [--days 30] [--keep 100] [--param dry_run=true]
  /harness prompt
  /harness tasks
  /harness runs [--last N]
  /harness hooks install|uninstall|status
  /harness env:check
  (opção global: --config CAMINHO)"""

    # ------------------------------------------------------------------
    def execute(self, args):
        args = list(args)

        config_path = None
        if "--config" in args:
            index = args.index("--config")
            if index + 1 < len(args):
                config_path = args[index + 1]
                del args[index : index + 2]

        sub = args[0] if args else "help"
        rest = args[1:]

        # Atalhos: `state save`, `notes draft`, `watch clip`, `kb export` -> `run state:save` ...
        if sub in ("state", "notes", "watch", "kb", "clean") and rest and not rest[0].startswith("--"):
            action, tail = rest[0], list(rest[1:])
            if sub == "state" and action == "load" and tail and not tail[0].startswith("--"):
                tail = ["--name", *tail]
            if sub == "notes" and action == "draft" and tail and not tail[0].startswith("--"):
                tail = ["--module", *tail]
            args = ["run", f"{sub}:{action}", *tail]
            sub, rest = args[0], args[1:]

        if sub in ("help", "--help", "-h"):
            print(self.get_usage())
            return True, {"help": True}

        # Operações de ciclo de vida (não exigem PyYAML no host).
        if sub == "install":
            return self._op(
                ops.install(
                    force="--force" in rest,
                    skip_docker="--skip-docker" in rest,
                    check_only="--check-only" in rest or "--check" in rest,
                    python_exe=self._install_python(rest),
                    with_rag="--with-rag" in rest,
                )
            )
        if sub == "config":
            info = ops.config_info(config_path)
            for key, value in info.items():
                print(f"{key}: {value}")
            return True, info
        if sub == "start":
            return self._op(
                ops.start(
                    with_rag="--rag" in rest,
                    no_docker="--no-docker" in rest,
                    config_path_arg=config_path,
                )
            )
        if sub == "stop":
            return self._op(
                ops.stop(
                    purge="--purge" in rest,
                    config_path_arg=config_path,
                )
            )
        if sub == "prepare":
            return self._op(
                ops.prepare(
                    full="--full" in rest,
                    with_rag="--rag" in rest,
                    sync="--sync" in rest,
                    no_docker="--no-docker" in rest,
                    config_path_arg=config_path,
                )
            )
        if sub == "preprocess":
            return self._op(
                ops.preprocess(
                    sync="--sync" in rest,
                    full="--full" in rest,
                    no_codeknow="--no-codeknow" in rest,
                    no_wiki="--no-wiki" in rest,
                    config_path_arg=config_path,
                )
            )

        try:
            self._ensure_runtime()

            if sub == "tasks":
                from .complements.harness.catalog import all_tasks

                specs = all_tasks()
                for spec in specs:
                    print(f"{spec.name:<14} [{spec.intent:<5}] {spec.description}")
                return True, {"count": len(specs)}
            if sub == "exec":
                return self._exec(config_path, rest)
            if sub == "run":
                return self._run(config_path, rest)
            if sub == "ask":
                return self._ask(config_path, rest)
            if sub == "prompt":
                return self._single(config_path, "prompt", {})
            if sub == "runs":
                return self._runs(config_path, rest)
            if sub == "hooks":
                return self._hooks(config_path, rest)
            if sub == "env:check":
                return self._single(config_path, "env:check", {})
        except Exception as exc:  # noqa: BLE001
            print(f"[harness] erro: {exc}")
            return False, {"error": str(exc)}

        print(f"[harness] subcomando desconhecido: {sub}")
        print(self.get_usage())
        return False, {"error": "subcomando desconhecido"}

    # ------------------------------------------------------------------
    def _ensure_runtime(self):
        from .complements.harness.bootstrap import ensure_deps

        if not ensure_deps():
            raise RuntimeError(
                "dependências do plugin não instaladas; rode '/harness install'"
            )

        from .complements.harness.catalog import load_tasks

        load_tasks()

    def _install_python(self, args: list[str]) -> str | None:
        """Extrai --python CAMINHO (ou --python=CAMINHO) do install."""
        for index, item in enumerate(args):
            if item == "--python" and index + 1 < len(args):
                return args[index + 1]
            if item.startswith("--python="):
                return item.split("=", 1)[1]
        return None

    def _op(self, result):
        if result.summary:
            print(result.summary)
        details = (result.details or "").strip()
        if details and details != result.summary.strip():
            print(details)
        return result.success, {
            "summary": result.summary,
            "status": result.status,
        }

    def _exec(self, config_path, args):
        from .complements.harness.engine import HarnessEngine

        yes = "--yes" in args
        dry_run = "--dry-run" in args

        source = "clip"
        path = None
        if "--file" in args:
            index = args.index("--file")
            if index + 1 < len(args):
                path = args[index + 1]
            source = "file"
        elif "--stdin" in args:
            source = "stdin"

        text = self._read_source(source, path)
        engine = HarnessEngine(config_path=config_path, interactive=True, yes=yes, dry_run=dry_run)
        results, error = engine.handle_text(text, yes_allowed=False)

        if error:
            print(f"[harness] {error}")
            return False, {"error": error}

        statuses = [item["status"] for item in results]
        ok = all(status == "success" for status in statuses)
        return ok, {"count": len(results), "statuses": statuses}

    def _run(self, config_path, args):
        task, params, flags = self._parse_run_args(args)
        if not task:
            print("[harness] informe a tarefa")
            return False, {"error": "tarefa ausente"}

        return self._single(
            config_path,
            task,
            params,
            yes_allowed=True,
            yes=flags["yes"],
            dry_run=flags["dry_run"],
        )

    def _single(
        self,
        config_path,
        task,
        params,
        yes_allowed=True,
        yes=False,
        dry_run=False,
    ):
        import yaml

        from .complements.harness.engine import HarnessEngine

        engine = HarnessEngine(
            config_path=config_path,
            interactive=True,
            yes=yes,
            dry_run=dry_run,
        )
        block = {"harness": 1, "task": task, "params": params or {}}
        raw = yaml.safe_dump(block, allow_unicode=True, sort_keys=False)
        _text, status = engine.handle_block(raw, yes_allowed=yes_allowed)
        return status == "success", {"status": status}

    def _ask(self, config_path, args):
        from .complements.harness.catalog import get_task
        from .complements.harness.engine import HarnessEngine
        from .complements.harness.task_types import TaskContext

        from .complements.harness import asking

        context = None
        budget = None
        question_parts = []
        index = 0
        while index < len(args):
            if args[index] == "--context" and index + 1 < len(args):
                context = args[index + 1]
                index += 2
            elif args[index] == "--budget" and index + 1 < len(args):
                try:
                    budget = int(args[index + 1])
                except ValueError:
                    print("[harness] --budget deve ser um número de tokens")
                    return False, {"error": "budget inválido"}
                index += 2
            else:
                question_parts.append(args[index])
                index += 1

        question = " ".join(question_parts).strip()
        if not question:
            print("[harness] informe a pergunta")
            return False, {"error": "pergunta ausente"}

        engine = HarnessEngine(config_path=config_path, interactive=True)
        output_cfg = engine.config.get("output") or {}
        context = context or str(output_cfg.get("ask_context") or asking.DEFAULT_CONTEXT)
        if budget is None and output_cfg.get("ask_budget"):
            budget = int(output_cfg["ask_budget"])
        chars_per_token = int(output_cfg.get("token_chars") or asking.DEFAULT_CHARS_PER_TOKEN)
        wanted = {item.strip() for item in context.split(",") if item.strip()}

        ctx = TaskContext(
            config=engine.config,
            workspace=engine.workspace,
            run_dir=engine.workspace,
        )

        sections = []

        if "notes" in wanted:
            from .complements.harness.util import notes_path

            found = asking.select_notes(notes_path(ctx), question)
            if found:
                text = "\n\n".join(f"### {name}\n\n{body.strip()}" for name, body, _ in found)
            else:
                text = "(nenhuma ficha casa com a pergunta; use `notes:draft` depois de entender o módulo)"
            sections.append(("notes", "Fichas revisadas", text))

        if "map" in wanted:
            sections.append(("map", "Mapa do código", self._map_context(engine)))

        if "skeleton" in wanted:
            sections.append(("skeleton", "Esqueleto do projeto", self._skeleton_context(engine)))

        if "rag" in wanted:
            spec = get_task("rag:search")
            if spec is not None:
                result = spec.handler(ctx, {"query": question, "top_k": 5})
                sections.append(("rag", "Contexto do RAG", result.details or result.summary))

        if "code" in wanted:
            symbol = self._identifier(question)
            spec = get_task("code:search")
            if spec is not None and symbol:
                result = spec.handler(ctx, {"pattern": symbol, "max_results": 10})
                sections.append(("code", "Ocorrências no código", result.details))
            else:
                sections.append(
                    (
                        "code",
                        "Ocorrências no código",
                        "(nenhum identificador reconhecido na pergunta; use code:search)",
                    )
                )

        if "db" in wanted:
            sections.append(("db", "Contexto do banco", self._db_context(engine)))

        if "docs" in wanted:
            sections.append(("docs", "Documentação importada", self._docs_context(engine)))

        prompt, usage = asking.fit_sections(question, sections, budget, chars_per_token)

        from .complements.harness import redact

        policy = redact.get_policy(engine.config)
        if redact.applies(policy, "ask"):
            prompt, stats = redact.redact_text(prompt, policy)
            if stats:
                prompt += f"\n\n[redact: {redact.format_stats(stats)}]\n"

        copied = False
        try:
            import pyperclip

            pyperclip.copy(prompt)
            copied = True
        except Exception:  # noqa: BLE001
            copied = False

        print(prompt)
        return True, {"copied": copied}

    def _db_context(self, engine, max_chars: int = 8000) -> str:
        """Resumo compacto do schema-catalog.json para o contexto do prompt."""
        import json
        import os

        path = os.path.join(engine.workspace, "knowledge", "db", "schema-catalog.json")
        if not os.path.isfile(path):
            return "(schema-catalog.json não encontrado; rode db:snapshot)"

        try:
            with open(path, "r", encoding="utf-8") as fh:
                catalog = json.load(fh)
        except (OSError, ValueError) as exc:  # noqa: BLE001
            return f"(falha ao ler o catálogo: {exc})"

        blocks = []
        for table in catalog.get("tables") or []:
            name = table.get("name", "?")
            columns = table.get("columns") or []
            cols = ", ".join(
                f"{column.get('name', '?')} {column.get('type', '?')}".rstrip()
                for column in columns
            )
            block = [f"### {name}", ""]
            if table.get("comment"):
                block.extend([f"_{table['comment']}_", ""])
            block.append(cols)
            blocks.append("\n".join(block))

        if not blocks:
            return "(nenhuma tabela no schema-catalog.json)"

        text = "\n\n".join(blocks)
        if len(text) > max_chars:
            from .complements.harness.formatter import cut_head

            text, _omitted = cut_head(
                text,
                max_chars,
                hint="Use `db:schema table=<nome>` para uma tabela específica.",
            )
        return text

    def _map_context(self, engine, max_chars: int = 20000) -> str:
        """Injeta o MAP.md (um índice por diretório) no prompt."""
        import os

        path = os.path.join(engine.workspace, "knowledge", "skeleton", "MAP.md")
        if not os.path.isfile(path):
            return "(MAP.md não encontrado; rode `code:skeleton`)"
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:  # noqa: BLE001
            return f"(falha ao ler o mapa: {exc})"
        if len(text) > max_chars:
            from .complements.harness.formatter import cut_head

            text, _omitted = cut_head(
                text,
                max_chars,
                hint="Use `code:skeleton level=dir path=<diretório>`.",
            )
        return text

    def _skeleton_context(self, engine, max_chars: int = 20000) -> str:
        """Injeta o SKELETON.md (mapa leve) no prompt."""
        import os

        path = os.path.join(engine.workspace, "knowledge", "skeleton", "SKELETON.md")
        if not os.path.isfile(path):
            return "(SKELETON.md não encontrado; rode `code:skeleton`)"
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:  # noqa: BLE001
            return f"(falha ao ler o esqueleto: {exc})"
        if len(text) > max_chars:
            from .complements.harness.formatter import cut_head

            text, _omitted = cut_head(
                text,
                max_chars,
                hint="Use `code:skeleton level=map` ou `level=dir path=<diretório>`.",
            )
        return text

    def _docs_context(self, engine, max_chars: int = 4000) -> str:
        """Lista os manuais/tickets importados (o texto vem do RAG ou do arquivo)."""
        import json
        import os

        path = os.path.join(engine.workspace, "knowledge", "docs", "manifest.json")
        if not os.path.isfile(path):
            return "(documentação não importada; rode `docs:import`)"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError) as exc:  # noqa: BLE001
            return f"(falha ao ler o manifesto: {exc})"

        items = manifest.get("files") or manifest.get("manuals") or []
        if isinstance(items, dict):
            items = list(items)
        lines = [f"- `{item}`" for item in items[:40]]
        if not lines:
            return "(nenhum arquivo no manifesto)"
        text = "\n".join(lines)
        if len(text) > max_chars:
            from .complements.harness.formatter import cut_head

            text, _omitted = cut_head(
                text, max_chars, hint="Use `rag:search` para localizar um manual."
            )
        return text

    def _identifier(self, question: str) -> str | None:
        """Primeiro candidato a símbolo/tabela na pergunta (para o code:search)."""
        import re

        stop = {
            "como",
            "onde",
            "qual",
            "quais",
            "para",
            "pelo",
            "pela",
            "este",
            "esta",
            "isso",
            "quando",
            "funciona",
            "sistema",
            "tabela",
            "codigo",
            "código",
        }
        candidates = [
            token
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", question)
            if token.lower() not in stop
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda token: (
                "_" in token or any(char.isupper() for char in token[1:]),
                len(token),
            ),
            reverse=True,
        )
        return candidates[0]

    def _hooks(self, config_path, args):
        from .complements.harness import hooks
        from .complements.harness.engine import HarnessEngine

        action = args[0] if args else "status"
        engine = HarnessEngine(config_path=config_path, interactive=False)

        if action == "install":
            installed = hooks.install(engine.config)
            print(f"hooks instalados: {', '.join(installed)}")
            return True, {"installed": installed}

        if action == "uninstall":
            removed = hooks.uninstall(engine.config)
            print(f"hooks removidos: {', '.join(removed) if removed else 'nenhum'}")
            return True, {"removed": removed}

        if action == "status":
            state = hooks.status(engine.config)
            for name in ("post-commit", "post-merge"):
                print(f"{name}: {'instalado' if state.get(name) else 'ausente'}")
            print(f"log: {state['log']}")
            return True, state

        print(f"[harness] acao de hooks desconhecida: {action}")
        return False, {"error": "acao desconhecida"}

    def _runs(self, config_path, args):
        from .complements.harness.engine import HarnessEngine

        count = 10
        if "--last" in args:
            index = args.index("--last")
            if index + 1 < len(args):
                try:
                    count = int(args[index + 1])
                except ValueError:
                    count = 10

        engine = HarnessEngine(config_path=config_path, interactive=True)
        records = engine.runs.last(count)
        for record in records:
            print(
                f"{record.get('id')}  {record.get('task'):<12} "
                f"{record.get('status'):<8} {record.get('duration_ms')}ms"
            )
        return True, {"count": len(records)}

    # ------------------------------------------------------------------
    def _read_source(self, source: str, path: str | None) -> str:
        if source == "file":
            if not path:
                raise ValueError("informe o caminho com --file")
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()

        if source == "stdin":
            return sys.stdin.read()

        import pyperclip

        return pyperclip.paste()

    def _parse_run_args(self, args):
        task = None
        params = {}
        flags = {"yes": False, "dry_run": False}

        index = 0
        while index < len(args):
            item = args[index]

            if item == "--yes":
                flags["yes"] = True
            elif item == "--dry-run":
                flags["dry_run"] = True
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
