from app.core.settings import get_settings


def content_preview(text: str | None) -> str:
    if not text:
        return ""
    limit = get_settings().log_content_preview_chars
    if limit <= 0:
        return f"<{len(text)} 字符>"
    preview = text[:limit]
    if len(text) > limit:
        preview += "…"
    return preview
