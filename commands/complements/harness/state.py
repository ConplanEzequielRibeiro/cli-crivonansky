"""Estado de tarefa (``crivonansky-state``): contrato, validação e prompt de retomada.

Permite continuar uma tarefa numa conversa nova do chat: o Claude encerra com um
bloco ``crivonansky-state``; o harness grava em ``<state.path>/estado/`` e depois
monta o prompt de abertura (estado + mapa). Funções puras.
"""

import os
import re
from datetime import date

import yaml

from .util import slugify

STATE_RE = re.compile(r"```crivonansky-state\s*\n(.*?)```", re.DOTALL)
REQUIRED = ("tarefa", "decisoes", "arquivos", "pendencias", "proximo_passo")
LIST_FIELDS = ("decisoes", "arquivos", "pendencias")
STATE_DIR = "estado"
FRONT_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)


class StateError(Exception):
    pass


def extract_state(text: str) -> str | None:
    """Conteúdo YAML do primeiro bloco ``crivonansky-state`` (ou ``None``)."""
    match = STATE_RE.search((text or "").replace("\r\n", "\n"))
    return match.group(1) if match else None


def parse_state(raw: str) -> dict:
    body = extract_state(raw)
    if body is None:
        body = (raw or "").replace("\r\n", "\n")
        # aceita também um arquivo de estado salvo (com frontmatter)
        match = FRONT_RE.match(body)
        if match:
            body = match.group(1)
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise StateError(f"YAML inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise StateError("o estado deve ser um mapa chave: valor")

    problems = []
    for key in REQUIRED:
        if key not in data:
            problems.append(f"campo obrigatório ausente: {key}")
    if "tarefa" in data and not str(data.get("tarefa") or "").strip():
        problems.append("tarefa vazia")
    for key in LIST_FIELDS:
        if key in data and not isinstance(data[key], list):
            problems.append(f"{key} deve ser uma lista")
    if "proximo_passo" in data and not str(data.get("proximo_passo") or "").strip():
        problems.append("proximo_passo vazio")
    for item in data.get("arquivos") or []:
        text = str(item).replace("\\", "/")
        if os.path.isabs(text) or ".." in text.split("/"):
            problems.append(f"arquivo fora do repositório: {item}")
    if problems:
        raise StateError("; ".join(problems))

    clean = {key: data[key] for key in REQUIRED}
    clean["tarefa"] = str(clean["tarefa"]).strip()
    clean["proximo_passo"] = str(clean["proximo_passo"]).strip()
    for key in LIST_FIELDS:
        clean[key] = [str(item) for item in clean[key]]
    return clean


def state_filename(state: dict, today: date | None = None) -> str:
    return f"{(today or date.today()).isoformat()}-{slugify(state['tarefa'])}.md"


def render_state(state: dict, today: date | None = None) -> str:
    meta = dict(state)
    meta["salvo_em"] = (today or date.today()).isoformat()
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False)
    lines = [f"---\n{front}---\n", f"# Estado: {state['tarefa']}\n"]
    for title, key in (("Decisões", "decisoes"), ("Arquivos", "arquivos"), ("Pendências", "pendencias")):
        lines.append(f"\n## {title}\n")
        lines += [f"- {item}" for item in state[key]] or ["- (nenhum)"]
    lines.append(f"\n## Próximo passo\n\n{state['proximo_passo']}\n")
    return "\n".join(lines)


def read_state(text: str) -> dict:
    return parse_state(text)


def list_states(folder: str) -> list[str]:
    path = os.path.join(folder, STATE_DIR)
    if not os.path.isdir(path):
        return []
    return sorted(name for name in os.listdir(path) if name.endswith(".md"))


def resume_prompt(state: dict, map_text: str = "") -> str:
    def bullets(items):
        return "\n".join(f"- {item}" for item in items) or "- (nenhum)"

    parts = [
        f"Vamos retomar a tarefa **{state['tarefa']}** de uma conversa anterior.",
        "",
        "## Decisões já tomadas",
        bullets(state["decisoes"]),
        "",
        "## Arquivos envolvidos",
        bullets(state["arquivos"]),
        "",
        "## Pendências",
        bullets(state["pendencias"]),
        "",
        "## Próximo passo",
        state["proximo_passo"],
    ]
    if map_text.strip():
        parts += ["", "## Mapa do código (índice)", map_text.strip()]
    parts += [
        "",
        "Você não tem acesso direto ao repositório: peça leituras com blocos `crivonansky` "
        "(`code:outline` → `code:symbol` → `code:read`). Não refaça as decisões acima sem um "
        "motivo explícito; confirme a hipótese antes do primeiro pedido.",
    ]
    return "\n".join(parts) + "\n"
