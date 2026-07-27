from __future__ import annotations


def public_analysis_error(value: object) -> str | None:
    """Translate internal analyzer failures into safe, actionable UI messages."""
    if value is None:
        return None

    error = str(value).strip()
    if not error:
        return None

    normalized = error.casefold()
    if (
        "not configured" in normalized
        or "configure mystery_atlas_ai_" in normalized
    ):
        return "AI 分析服务尚未配置，请联系管理员完成配置后重试。"
    if any(
        marker in normalized
        for marker in ("401", "unauthorized", "authentication", "api key")
    ):
        return "AI 分析服务认证失败，请联系管理员检查 API Key 和服务地址后重试。"
    if any(
        marker in normalized
        for marker in (
            "ssl",
            "urlopen",
            "connection",
            "timed out",
            "timeout",
            "unexpected_eof",
            "unexpected eof",
        )
    ):
        return "暂时无法连接 AI 分析服务，请稍后重试。"
    if any(
        marker in normalized
        for marker in ("json", "validation", "model response")
    ):
        return "AI 返回的数据格式不完整，请稍后重新分析。"
    return "分析任务失败，请稍后重试。"
