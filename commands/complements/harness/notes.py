"""Fichas de conhecimento (notes): esquema, hash de fonte e validação.

Uma ficha é um Markdown com frontmatter YAML e seções fixas, revisado por
humano. ``hash_fonte`` ancora a ficha nos arquivos citados: quando algum muda,
a ficha fica *velha* (``notes:stale``). Funções puras, sem I/O de rede.
"""

import hashlib
import os
import re
from datetime import datetime

import yaml

REQUIRED_FIELDS = ("modulo", "tags", "tabelas", "arquivos", "hash_fonte", "revisado", "atualizado_em")
LIST_FIELDS = ("tags", "tabelas", "arquivos")
SECTIONS = (
    "Responsabilidade",
    "Pontos de entrada",
    "Fluxo principal",
    "Regras de negócio",
    "Armadilhas",
    "Ligações",
)
FRONT_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
SLUG_RE = re.compile(r"[^a-z0-9]+")
MODEL_NAME = "_modelo.md"
HASH_LEN = 16


class NoteError(Exception):
    """Ficha inválida; a mensagem lista todos os problemas."""


def _norm(text: str) -> str:
    return (text or "").replace("\r\n", "\n").lstrip("﻿")


def slugify(value: str) -> str:
    plain = re.sub(r"[^\x00-\x7f]", lambda m: _ascii(m.group(0)), str(value).lower())
    return SLUG_RE.sub("-", plain).strip("-") or "ficha"


def _ascii(char: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode("ascii")


def split_note(text: str) -> tuple[dict, str]:
    """Separa frontmatter e corpo; levanta ``NoteError`` se o frontmatter faltar."""
    text = _norm(text)
    match = FRONT_RE.match(text)
    if not match:
        raise NoteError("frontmatter ausente (bloco `---` no início da ficha)")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise NoteError(f"frontmatter YAML inválido: {exc}") from exc
    if not isinstance(meta, dict):
        raise NoteError("frontmatter deve ser um mapa chave: valor")
    return meta, text[match.end() :]


def validate_meta(meta: dict, body: str = "") -> list[str]:
    problems: list[str] = []
    for key in REQUIRED_FIELDS:
        if key not in meta:
            problems.append(f"campo obrigatório ausente: {key}")
    if "modulo" in meta and not str(meta.get("modulo") or "").strip():
        problems.append("modulo vazio")
    for key in LIST_FIELDS:
        if key in meta and not isinstance(meta[key], list):
            problems.append(f"{key} deve ser uma lista")
    if "revisado" in meta and not isinstance(meta["revisado"], bool):
        problems.append("revisado deve ser true ou false")
    for key in ("arquivos",):
        for item in meta.get(key) or []:
            text = str(item).replace("\\", "/")
            if os.path.isabs(text) or ".." in text.split("/"):
                problems.append(f"arquivo fora do repositório: {item}")
    if body:
        headings = {m.strip().lower() for m in re.findall(r"^##\s+(.+?)\s*$", body, re.M)}
        for section in SECTIONS:
            if section.lower() not in headings:
                problems.append(f"seção ausente: ## {section}")
    return problems


def parse_note(text: str) -> tuple[dict, str]:
    """Parse + validação completa; ``NoteError`` com todos os problemas."""
    meta, body = split_note(text)
    problems = validate_meta(meta, body)
    if problems:
        raise NoteError("; ".join(problems))
    return meta, body


def source_hash(repo: str, files: list) -> str:
    """Hash estável do conteúdo atual dos arquivos citados (EOL-insensível)."""
    digest = hashlib.sha256()
    for rel in sorted(str(item).replace("\\", "/") for item in files):
        digest.update(rel.encode("utf-8") + b"\0")
        try:
            with open(os.path.join(repo, rel), "rb") as fh:
                digest.update(fh.read().replace(b"\r\n", b"\n"))
        except OSError:
            digest.update(b"<ausente>")
        digest.update(b"\0")
    return digest.hexdigest()[:HASH_LEN]


def changed_files(repo: str, files: list, stored_hash: str) -> list[str]:
    """Arquivos ausentes (ou todos, se o hash não bate) — base do ``notes:stale``."""
    if source_hash(repo, files) == stored_hash:
        return []
    missing = [str(f) for f in files if not os.path.isfile(os.path.join(repo, str(f)))]
    return missing or [str(f) for f in files]


def render_note(meta: dict, body: str) -> str:
    ordered = {key: meta[key] for key in REQUIRED_FIELDS if key in meta}
    ordered.update({k: v for k, v in meta.items() if k not in ordered})
    front = yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{front}---\n{_norm(body).lstrip(chr(10))}".rstrip("\n") + "\n"


def stamp(meta: dict, repo: str, now: datetime | None = None) -> dict:
    """Recalcula ``hash_fonte`` e ``atualizado_em``."""
    meta = dict(meta)
    meta["hash_fonte"] = source_hash(repo, list(meta.get("arquivos") or []))
    meta["atualizado_em"] = (now or datetime.now()).strftime("%Y-%m-%d")
    return meta


def skeleton_body(prefill: dict | None = None) -> str:
    prefill = prefill or {}
    parts = []
    for section in SECTIONS:
        parts.append(f"## {section}\n\n{prefill.get(section, '<!-- preencher -->')}\n")
    return "\n".join(parts)


def model_text() -> str:
    meta = {
        "modulo": "nome-do-modulo",
        "tags": [],
        "tabelas": [],
        "arquivos": [],
        "hash_fonte": "",
        "revisado": False,
        "atualizado_em": "",
    }
    return render_note(meta, "# Título do módulo\n\n" + skeleton_body())


def note_filename(modulo: str) -> str:
    return slugify(modulo) + ".md"
