"""Tarefa prompt: monta o prompt de instrução do LLM com o catálogo vivo."""

from commands.complements.harness_core import packs
from commands.complements.harness_core.catalog import register
from commands.complements.harness_core.policy import DEFAULT_LLM_DENIED
from commands.complements.harness_core.task_types import TaskResult, TaskSpec

# Tamanho máximo dos parâmetros/descrição em cada linha do catálogo.
MAX_PARAMS = 6
MAX_DESCRIPTION = 100
CATALOG_PLACEHOLDER = "__CATALOGO__"

INSTRUCTIONS = """Você está conectado a um harness local de desenvolvimento de um sistema legado (PHP, MySQL, JS).
Você NÃO tem acesso direto a arquivos, terminal ou banco de dados.

Para pedir uma ação, responda com UM ou mais blocos de código no formato:

```crivonansky
harness: 1
task: <tarefa do catálogo>
params: { ... }
```

__CATALOGO__
Regras:
1. Use apenas tarefas do catálogo acima. As tarefas listadas como negadas a blocos do
   LLM serão recusadas: só o usuário as executa pela linha de comando.
2. Navegue por busca determinística (JIT), não por resumo. O mapa do código é só um
   índice: comece por ele, depois siga `code:outline` -> `code:symbol`
   -> `code:read` com intervalo de linhas. Nunca peça o repositório inteiro.
   Antes de cada pedido, declare em uma linha a hipótese que ele testa.
3. Faça no máximo 6 blocos por pergunta. Não repita uma busca com o mesmo pattern;
   se precisar de mais contexto, mude `path`, `glob` ou o pattern.
4. Sempre cite `arquivo:linha` nas conclusões. Baseie-se apenas nos blocos recebidos.
5. Se um resultado vier com `[truncado: ...]` ou `truncated: true`, siga a dica de
   continuação indicada (`path`, `start`/`end`, `max_results`, `level=dir`) em vez de
   supor o que faltou ou repetir a mesma chamada. O esqueleto é só um índice: para
   detalhar um diretório use `code:skeleton level=dir path=<diretório>`.
6. Prefira tarefas de leitura para investigar antes de propor mudanças.
7. Para alterar código, proponha o diff unificado e informe `branch` (nunca uma branch
   protegida). Quem aplica é o usuário, com `/harness-patch run patch:apply --file <diff>`;
   o harness preserva encoding/CRLF/BOM do arquivo.
8. Após emitir blocos, PARE e aguarde o bloco ```crivonansky-result.
9. Nunca invente resultados. Se o status for failure/error/denied/timeout, leia o
   summary/details antes de tentar de novo.
10. Ao terminar (ou ao pedir para parar), encerre com UM bloco de estado, para a tarefa
    poder ser retomada numa conversa nova:

```crivonansky-state
tarefa: <nome curto>
decisoes: [<o que ficou decidido>]
arquivos: [<caminhos relativos ao repositório>]
pendencias: [<o que falta>]
proximo_passo: <uma frase>
```
11. Dados pessoais e segredos aparecem mascarados nos resultados (`[redact: ...]`);
    não tente contorná-los."""


def _short(text: str, limit: int = MAX_DESCRIPTION) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _params(spec) -> str:
    """``(obrigatórios, opcionais?)`` da tarefa, sem estourar a linha."""
    if spec is None:
        return ""
    names = [str(name) for name in (spec.required or [])]
    names += [f"{name}?" for name in (spec.optional or [])]
    if not names:
        return ""
    if len(names) > MAX_PARAMS:
        names = names[:MAX_PARAMS] + ["…"]
    return f" ({', '.join(names)})"


def _task_lines(pack: str, specs: dict) -> list[str]:
    lines = []
    for name in packs.pack_tasks(pack):
        spec = specs.get(name)
        # ``(read)`` em vez de ``[read]``: colchetes são interpretados como markup
        # no TUI (Rich) e sumiriam da saída exibida.
        intent = f" ({spec.intent})" if spec is not None else ""
        description = ""
        if spec is not None and spec.description:
            description = f" — {_short(spec.description)}"
        lines.append(f"- `{name}`{intent}{_params(spec)}{description}")
    return lines


def _denied(config: dict) -> str:
    """Frase com as tarefas que um bloco do LLM não executa (policy + padrão dos packs)."""
    policy = (config or {}).get("policy") or {}
    allowed = policy.get("llm_allowed_tasks")
    if allowed is not None:
        names = ", ".join(f"`{item}`" for item in allowed) or "(nenhuma)"
        return f"Blocos do LLM só executam `policy.llm_allowed_tasks`: {names}"
    denied = policy.get("llm_denied_tasks")
    if denied is None:
        denied = set(DEFAULT_LLM_DENIED)
        for manifest in packs.manifests().values():
            denied.update(getattr(manifest, "DEFAULT_LLM_DENIED", ()) or ())
    names = ", ".join(f"`{task}`" for task in sorted(str(item) for item in denied))
    return (
        f"Blocos do LLM NÃO executam: {names or '(nenhuma)'} — "
        "só o usuário, pela linha de comando"
    )


def _catalog(ctx) -> str:
    """Catálogo montado na execução: nunca fica desatualizado em relação aos packs."""
    from commands.complements.harness_core.catalog import all_tasks

    specs = {spec.name: spec for spec in all_tasks()}
    manifests = packs.manifests()
    config = getattr(ctx, "config", None) or {}

    lines = ["## Catálogo (lido do registro a cada execução)", ""]
    lines.append("Blocos enviados a `/harness`:")
    lines.extend(_task_lines("harness", specs))
    lines += [
        "",
        "Tarefas de core, aceitas por qualquer comando: `env:check`, `prompt`.",
    ]

    others = []
    for pack in packs.KNOWN_PACKS:
        if pack == "harness" or not packs.pack_tasks(pack):
            continue
        if not packs.is_enabled(config, pack):
            continue
        command = getattr(manifests[pack], "COMMAND", pack)
        names = ", ".join(f"`{task}`" for task in packs.pack_tasks(pack))
        others.append(f"- `/{command}`: {names}")
    if others:
        lines += ["", "Outros comandos executam as próprias tarefas (não peça por `/harness`):"]
        lines.extend(others)

    lines += [
        "",
        f"{_denied(config)}.",
        "",
    ]
    return "\n".join(lines)


def handle(ctx, params):
    prompt = INSTRUCTIONS.replace(CATALOG_PLACEHOLDER, _catalog(ctx))
    return TaskResult(True, "prompt do LLM com o catálogo atualizado", details=prompt)


register(
    TaskSpec(
        name="prompt", pack="core",
        intent="read",
        description="Monta o prompt de instrução do LLM com o catálogo vivo",
        required=[],
        optional=[],
        handler=handle,
    )
)
