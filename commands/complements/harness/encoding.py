"""Encoding das fontes do legado, resolvido pelo perfil de stack."""


def source_encoding(ctx) -> str:
    """Encoding configurado em ``legacy.encoding``/perfil; padrão UTF-8."""
    try:
        from .profiles import resolve_profile

        return resolve_profile(getattr(ctx, "config", None) or {}).encoding
    except Exception:  # noqa: BLE001 - config inválida é tratada pela tarefa
        return "utf-8"
