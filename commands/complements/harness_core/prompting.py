"""Prompt curto por pack para os comandos fora do mapeamento."""

from . import packs


def render(pack: str) -> str:
    manifest = packs.manifests()[pack]
    tasks = "\n".join(f"- `{task}`" for task in manifest.TASKS)
    denied = ", ".join(manifest.DEFAULT_LLM_DENIED) or "(nenhuma)"
    return (
        f"Você está usando o plugin `/{manifest.COMMAND}` do harness local.\n"
        f"{manifest.DESCRIPTION}\n\n"
        "Para pedir uma ação, responda com UM bloco:\n\n"
        "```crivonansky\n"
        "harness: 1\n"
        "task: <tarefa>\n"
        "params: { ... }\n"
        "```\n\n"
        f"Tarefas do pack:\n{tasks}\n\n"
        "Tarefas de core disponíveis: `env:check`, `prompt`.\n"
        f"Blocos do LLM não executam: {denied}.\n"
        "Escritas pedem confirmação; resultados vêm no bloco ```crivonansky-result.\n"
    )
