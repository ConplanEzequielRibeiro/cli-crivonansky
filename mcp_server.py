"""Servidor MCP (stdio) que expõe o Crivonansky ao OpenCode e a outros clientes.

Fala JSON-RPC 2.0 / MCP em stdin/stdout (uma mensagem JSON por linha) e executa
o CLI do Crivonansky por subprocesso. Não tem dependências externas: qualquer
Python 3.10+ consegue rodá-lo.

Configuração no OpenCode (``.opencode/opencode.jsonc``)::

    {
      "mcp": {
        "servers": {
          "crivonansky": {
            "type": "local",
            "command": ["C:/projetos/cli-crivonansky/.venv/Scripts/python.exe",
                        "C:/projetos/cli-crivonansky/mcp_server.py"],
            "cwd": "C:/projetos/cli-crivonansky"
          }
        }
      }
    }

Variáveis de ambiente (todas opcionais):

* ``CRIVONANSKY_PYTHON``    interpretador que roda o CLI (padrão: venv do repo);
* ``CRIVONANSKY_CLI``       caminho do ``crivonansky.py``;
* ``CRIVONANSKY_CWD``       diretório de trabalho do CLI;
* ``CRIVONANSKY_CONFIG``    ``harness.yaml`` alternativo (``--config``);
* ``CRIVONANSKY_TIMEOUT``   segundos por chamada (padrão: 900);
* ``CRIVONANSKY_MAX_CHARS`` corte do texto devolvido (padrão: 60000);
* ``CRIVONANSKY_ALLOW_WRITE`` ``1`` habilita tarefas de escrita (com ``--yes``);
* ``CRIVONANSKY_MCP_DEBUG`` ``1`` escreve logs de diagnóstico em stderr.

Sem ``CRIVONANSKY_ALLOW_WRITE=1`` apenas tarefas ``read`` são executadas; as de
escrita voltam como erro explicativo. Mesmo com a variável ligada, recomenda-se
restringir as ferramentas pelas permissões do OpenCode.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

SERVER_NAME = "crivonansky"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"
ROOT = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CLI = os.path.join(ROOT, "crivonansky.py")


def _default_python() -> str:
    if os.name == "nt":
        candidate = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    else:
        candidate = os.path.join(ROOT, ".venv", "bin", "python")
    return candidate if os.path.isfile(candidate) else sys.executable


PYTHON = os.environ.get("CRIVONANSKY_PYTHON") or _default_python()
CLI = os.environ.get("CRIVONANSKY_CLI") or DEFAULT_CLI
CWD = os.environ.get("CRIVONANSKY_CWD") or ROOT
CONFIG = os.environ.get("CRIVONANSKY_CONFIG") or ""
TIMEOUT = int(os.environ.get("CRIVONANSKY_TIMEOUT") or 900)
MAX_CHARS = int(os.environ.get("CRIVONANSKY_MAX_CHARS") or 60_000)
ALLOW_WRITE = os.environ.get("CRIVONANSKY_ALLOW_WRITE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEBUG = os.environ.get("CRIVONANSKY_MCP_DEBUG", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

INSTRUCTIONS = """O servidor `crivonansky` expõe o harness do sistema legado.

Navegação recomendada:
1. `crivonansky_tasks` para ver as tarefas e parâmetros.
2. `crivonansky_run` com `code:skeleton` (`level=map`) para o mapa por diretório.
   Em repositórios grandes use `level=part`/`part=<N>` (mapa completo dividido)
   ou `level=dir`/`path=<diretório>` antes de ler arquivos inteiros.
3. `code:search`, `code:read`, `code:outline` e `code:symbol` para o código.
4. Depois do skeleton, `db:links` liga SQL embutido às tabelas; `db:schema` e
   `db:query` (somente leitura) respondem sobre o banco.
5. `crivonansky_ask` monta um prompt com contexto (mapa, notas, schema, docs).

Tarefas `read` rodam direto. Tarefas `write` só existem quando o servidor foi
iniciado com `CRIVONANSKY_ALLOW_WRITE=1`; nesse caso confirme com o usuário antes
de executar (notas, patches, limpeza de artefatos etc.). O `crivonansky_exec`
aceita blocos ```crivonansky e aplica a política do harness (sem shell/py/docker
e sem escrita sem confirmação).
"""


# ---------------------------------------------------------------------------
# Catálogo de tarefas (intent/params) — carregado sob demanda
# ---------------------------------------------------------------------------
_TASKS: dict[str, dict] | None = None
_TASKS_ERROR = ""


def _catalog() -> dict[str, dict] | None:
    global _TASKS, _TASKS_ERROR
    if _TASKS is not None:
        return _TASKS
    if _TASKS_ERROR:
        return None
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from commands.complements.harness import bootstrap

        bootstrap.ensure_deps()
        from commands.complements.harness.catalog import all_tasks, load_tasks

        load_tasks()
        _TASKS = {
            spec.name: {
                "intent": spec.intent,
                "description": spec.description,
                "required": list(spec.required),
                "optional": list(spec.optional),
            }
            for spec in all_tasks()
        }
    except Exception as exc:  # noqa: BLE001 - catálogo é opcional
        _TASKS_ERROR = f"{type(exc).__name__}: {exc}"
        _log(f"catálogo indisponível: {_TASKS_ERROR}")
    return _TASKS


# ---------------------------------------------------------------------------
# Execução do CLI
# ---------------------------------------------------------------------------
def _stringify(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(_stringify(item) for item in value)
    return str(value)


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    newline = cut.rfind("\n")
    if newline > MAX_CHARS * 0.8:
        cut = cut[:newline]
    remaining = len(text) - len(cut)
    return (
        cut
        + f"\n\n[truncado: {remaining} caractere(s); reduza com params "
        "(ex.: level=dir/path, start/end) ou aumente CRIVONANSKY_MAX_CHARS]"
    )


def _invoke(argv: list[str], stdin_text: str | None = None) -> tuple[str, bool]:
    """Roda ``crivonansky.py harness <argv>`` e devolve ``(texto, is_error)``."""
    command = [PYTHON, CLI, "harness"]
    if CONFIG:
        command += ["--config", CONFIG]
    command += argv + ["--no-clipboard"]

    environment = os.environ.copy()
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    _log("exec: " + " ".join(command))

    try:
        process = subprocess.run(
            command,
            cwd=CWD,
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return (
            f"timeout após {TIMEOUT}s ao executar `harness {argv[0]}`; "
            "aumente CRIVONANSKY_TIMEOUT ou use parâmetros mais específicos.",
            True,
        )
    except OSError as exc:
        return f"falha ao executar o CLI ({PYTHON}): {exc}", True

    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()
    text = stdout or ("(sem saída)" if process.returncode == 0 else "")
    if stderr and (process.returncode != 0 or not stdout):
        text = (text + "\n\n[stderr]\n" + stderr).strip()
    if process.returncode != 0 and not text:
        text = f"exit code {process.returncode}: {stderr or 'sem detalhes'}"

    return _truncate(text), process.returncode != 0


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------
def tool_tasks(_arguments: dict) -> tuple[str, bool]:
    catalog = _catalog()
    if catalog is None:
        return (
            "não foi possível carregar o catálogo do harness: "
            f"{_TASKS_ERROR or 'plugin não instalado'}. Rode `harness install`.",
            True,
        )
    lines = ["Tarefas do harness (nome [intent] descrição — parâmetros):", ""]
    for name, meta in sorted(catalog.items()):
        params = list(meta.get("required") or []) + list(meta.get("optional") or [])
        suffix = f" — {', '.join(params)}" if params else ""
        lines.append(f"- `{name}` [{meta['intent']}] {meta['description']}{suffix}")
    return "\n".join(lines), False


def tool_run(arguments: dict) -> tuple[str, bool]:
    task = str(arguments.get("task") or "").strip()
    if not task:
        return "parâmetro obrigatório: task (veja `crivonansky_tasks`).", True

    params = arguments.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return "params deve ser um objeto {nome: valor}.", True

    catalog = _catalog()
    meta = (catalog or {}).get(task)
    if catalog is not None and meta is None:
        import difflib

        close = difflib.get_close_matches(task, catalog.keys(), n=5)
        hint = f" Próximas: {', '.join(close)}." if close else ""
        return f"tarefa desconhecida: {task}.{hint}", True

    write_task = bool(meta and meta.get("intent") != "read")
    if write_task and not ALLOW_WRITE:
        return (
            f"a tarefa `{task}` é de escrita e está bloqueada neste servidor. "
            "Peça ao usuário para habilitar `CRIVONANSKY_ALLOW_WRITE=1` (e "
            "reinicie o MCP) ou execute pela CLI com `--yes`.",
            True,
        )

    argv = ["run", task]
    for key, value in params.items():
        argv += ["--param", f"{key}={_stringify(value)}"]
    if arguments.get("dry_run"):
        argv.append("--dry-run")
    if write_task:
        argv.append("--yes")
    return _invoke(argv)


def tool_exec(arguments: dict) -> tuple[str, bool]:
    text = arguments.get("text")
    if not isinstance(text, str) or not text.strip():
        return "parâmetro obrigatório: text (bloco ```crivonansky).", True
    argv = ["exec", "--stdin"]
    if arguments.get("dry_run"):
        argv.append("--dry-run")
    return _invoke(argv, stdin_text=text)


def tool_ask(arguments: dict) -> tuple[str, bool]:
    question = str(arguments.get("question") or "").strip()
    if not question:
        return "parâmetro obrigatório: question.", True
    argv = ["ask", question]
    context = arguments.get("context")
    if context:
        argv += ["--context", str(context)]
    budget = arguments.get("budget")
    if budget:
        try:
            argv += ["--budget", str(int(budget))]
        except (TypeError, ValueError):
            return "budget deve ser um inteiro (tokens).", True
    return _invoke(argv)


TOOLS = [
    {
        "name": "tasks",
        "description": "Lista as tarefas do harness (code:*, db:*, state:*, ...) com intent e parâmetros.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "run",
        "description": (
            "Executa uma tarefa do harness. Ex.: code:skeleton (level=map|dir|part), "
            "code:search, code:read, code:symbol, db:links, db:schema, db:query, env:check."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Nome da tarefa (code:skeleton, db:links...)"},
                "params": {
                    "type": "object",
                    "description": "Parâmetros da tarefa (ex.: {level: 'map'}).",
                    "additionalProperties": True,
                },
                "dry_run": {"type": "boolean", "description": "Não executa; só valida."},
            },
            "required": ["task"],
            "additionalProperties": False,
        },
    },
    {
        "name": "exec",
        "description": (
            "Executa blocos ```crivonansky``` pela política do harness "
            "(shell/py/docker bloqueados; escrita exige confirmação)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto com um ou mais blocos crivonansky."},
                "dry_run": {"type": "boolean"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ask",
        "description": "Monta um prompt com contexto do harness (mapa, notas, banco, docs, RAG) e o devolve.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "context": {
                    "type": "string",
                    "description": "Lista separada por vírgula: map,db,code,docs,rag,skeleton.",
                },
                "budget": {"type": "integer", "description": "Orçamento em tokens."},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
]

HANDLERS = {
    "tasks": tool_tasks,
    "run": tool_run,
    "exec": tool_exec,
    "ask": tool_ask,
}


# ---------------------------------------------------------------------------
# JSON-RPC / MCP
# ---------------------------------------------------------------------------
def _log(message: str) -> None:
    if DEBUG:
        print(f"[crivonansky-mcp] {message}", file=sys.stderr, flush=True)


def _response(message_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _initialize(message: dict) -> dict:
    params = message.get("params") or {}
    requested = params.get("protocolVersion")
    version = requested if isinstance(requested, str) and requested else PROTOCOL_VERSION
    return _response(
        message.get("id"),
        {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        },
    )


def handle(message) -> list[dict]:
    """Processa uma mensagem e devolve as respostas (lista vazia = notificação)."""
    if isinstance(message, list):  # JSON-RPC batch
        responses = []
        for item in message:
            responses.extend(handle(item))
        return responses
    if not isinstance(message, dict):
        return [_error(None, -32600, "requisição inválida")]

    method = message.get("method")
    message_id = message.get("id")
    is_notification = "id" not in message

    if method == "initialize":
        return [_initialize(message)]
    if method in ("notifications/initialized", "initialized"):
        return []
    if method == "ping":
        return [] if is_notification else [_response(message_id, {})]
    if method in ("tools/list", "tools/listChanged"):
        return [] if is_notification else [_response(message_id, {"tools": TOOLS})]
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            return [_error(message_id, -32602, f"ferramenta desconhecida: {name}")]
        try:
            text, is_error = handler(arguments if isinstance(arguments, dict) else {})
        except Exception as exc:  # noqa: BLE001 - erro vira resultado da tool
            _log(f"erro em {name}: {exc!r}")
            text, is_error = f"erro interno em {name}: {exc}", True
        return [
            _response(
                message_id,
                {"content": [{"type": "text", "text": text}], "isError": bool(is_error)},
            )
        ]
    if method in ("resources/list",):
        return [] if is_notification else [_response(message_id, {"resources": []})]
    if method in ("resources/templates/list",):
        return [] if is_notification else [_response(message_id, {"resourceTemplates": []})]
    if method in ("prompts/list",):
        return [] if is_notification else [_response(message_id, {"prompts": []})]

    if is_notification:
        return []
    return [_error(message_id, -32601, f"método não suportado: {method}")]


def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _log(f"iniciado (cli={CLI}, cwd={CWD}, allow_write={ALLOW_WRITE})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _send(_error(None, -32700, f"JSON inválido: {exc}"))
            continue
        for payload in handle(message):
            _send(payload)


def selftest() -> int:
    """Imprime o handshake e as ferramentas (para testar sem um cliente MCP)."""
    print(json.dumps(_initialize({"id": 1, "params": {}}), ensure_ascii=False, indent=2))
    print(json.dumps(_response(2, {"tools": TOOLS}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    try:
        serve()
    except KeyboardInterrupt:
        raise SystemExit(0)
