"""Utilitários compartilhados pelas tarefas."""

import os

from .config import get_legacy_path, resolve_path as _resolve_config_path


def legacy_repo(ctx) -> str:
    return os.path.abspath(get_legacy_path(ctx.config, "repo_path", "."))


def workspace(ctx) -> str:
    return os.path.abspath(ctx.workspace)


def notes_path(ctx) -> str:
    """Pasta das fichas: ``knowledge.notes_path`` ou ``workspace/knowledge/notes``."""
    configured = ((ctx.config or {}).get("knowledge") or {}).get("notes_path")
    if configured:
        return os.path.abspath(_resolve_config_path(ctx.config, str(configured)))
    return os.path.join(workspace(ctx), "knowledge", "notes")


def allowed_roots(ctx) -> list[str]:
    raw = (ctx.config.get("policy") or {}).get("allowed_roots") or []
    repo = legacy_repo(ctx)
    ws = workspace(ctx)
    roots = []
    for item in raw:
        value = str(item).replace("${LEGACY_REPO}", repo).replace("${HARNESS_WORKSPACE}", ws)
        roots.append(os.path.abspath(value))
    if not roots:
        roots = [repo, ws]
    notes = notes_path(ctx)
    if notes not in roots:
        roots.append(notes)
    return roots


def is_within(path: str, roots: list[str]) -> bool:
    path = os.path.abspath(path)
    for root in roots:
        try:
            if os.path.commonpath([path, root]) == root:
                return True
        except ValueError:
            continue
    return False


def resolve_path(ctx, path: str) -> str:
    if os.path.isabs(path):
        return os.path.abspath(path)

    for base in (legacy_repo(ctx), workspace(ctx)):
        candidate = os.path.abspath(os.path.join(base, path))
        if os.path.exists(candidate):
            return candidate

    return os.path.abspath(os.path.join(legacy_repo(ctx), path))


def ensure_allowed(ctx, path: str) -> str:
    resolved = resolve_path(ctx, path)
    if not is_within(resolved, allowed_roots(ctx)):
        raise PermissionError(f"caminho fora das raízes permitidas: {path}")
    return resolved


def as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def looks_like_path(value: str | None) -> bool:
    """True quando o valor é um caminho (e não um nome de comando do PATH)."""
    if not value:
        return False
    return (
        os.path.isabs(value)
        or "/" in value
        or "\\" in value
        or value.lower().endswith(".exe")
    )


def as_bool(value, default: bool = False) -> bool:
    """Aceita bool do YAML e as formas textuais vindas de --param/CLI."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def read_text(path: str, encoding: str = "utf-8") -> str:
    """Lê um texto tentando UTF-8 primeiro e caindo para ``encoding``/latin-1.

    Dumps e fontes de legado Windows costumam vir em cp1252/latin-1 (ou com
    BOM). A ordem UTF-8 -> configurado -> cp1252 -> latin-1 evita mojibake nos
    dois sentidos, e latin-1 nunca falha (último recurso).
    """
    with open(path, "rb") as fh:
        raw = fh.read()

    text = _decode(raw, encoding)
    return text[1:] if text.startswith("\ufeff") else text


def _decode(raw: bytes, encoding: str) -> str:
    configured = (encoding or "utf-8").strip()
    normalized = configured.lower().replace("_", "-")

    candidates = ["utf-8"]
    if normalized not in ("utf-8", "utf8", "auto"):
        candidates.append(configured)
    candidates.extend(["cp1252", "latin-1"])

    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue

    return raw.decode("utf-8", errors="replace")


def source_encoding(ctx) -> str:
    """Encoding configurado no perfil de stack (``legacy.encoding``)."""
    try:
        from .profiles import resolve_profile

        return resolve_profile(getattr(ctx, "config", None) or {}).encoding
    except Exception:  # noqa: BLE001 - config inválida é tratada pela tarefa
        return "utf-8"


def write_text(path: str, content: str) -> None:
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def write_json(path: str, data) -> None:
    import json

    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
