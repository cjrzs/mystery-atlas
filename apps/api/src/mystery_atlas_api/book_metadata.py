import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from .config import Settings, get_settings
from .parsers import ParsedBook
from .tagging import normalize_book_tags

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BookMetadata:
    title: str
    author: str
    publisher: str | None
    translator: str | None
    isbn: str | None
    tags: list[str]


def clean_json_response(content: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    payload = json.loads(cleaned)
    return payload if isinstance(payload, dict) else {}


def clean_optional_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    if cleaned.lower() in {"", "null", "none", "unknown", "未知", "未识别"}:
        return None
    return cleaned[:limit]


def fallback_metadata(parsed: ParsedBook) -> BookMetadata:
    return BookMetadata(
        title=clean_optional_text(parsed.title, 300) or "未命名作品",
        author=clean_optional_text(parsed.author, 200) or "作者待识别",
        publisher=clean_optional_text(parsed.publisher, 200),
        translator=clean_optional_text(parsed.translator, 200),
        isbn=clean_optional_text(parsed.isbn, 32),
        tags=normalize_book_tags(parsed.tags),
    )


def ai_request_payload(
    parsed: ParsedBook,
    current: BookMetadata,
    settings: Settings,
    *,
    include_cover: bool,
) -> bytes:
    prompt = (
        "你是书籍档案元数据识别员。请根据结构化元数据、封面、序章、版权页和目录内容，"
        "识别书名、作者、出版社、译者、ISBN 和主题标签。只能填写有明确证据的信息；"
        "不确定的可选字段必须返回 null，不得根据常识猜测。标签返回 2 到 6 个简短中文词，"
        "避免人物名、剧透和完整句子。"
        '只返回 JSON：{"title":"书名或null","author":"作者或null",'
        '"publisher":"出版社或null","translator":"译者或null","isbn":"ISBN或null",'
        '"tags":["标签1","标签2"]}。\n\n'
        f"文件解析候选：{json.dumps(current.__dict__, ensure_ascii=False)}\n\n"
        f"序章、版权页或目录文本：\n{parsed.metadata_context[:8000]}"
    )
    user_content: str | list[dict[str, Any]] = prompt
    if include_cover and parsed.cover_data_url:
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": parsed.cover_data_url}},
        ]
    body: dict[str, Any] = {
        "model": settings.ai_reading_model,
        "messages": [
            {"role": "system", "content": "只输出符合要求的 JSON 对象。"},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
    }
    if settings.ai_reading_model == "kimi-k3":
        body["reasoning_effort"] = "low"
    else:
        body["temperature"] = 0.1
    return json.dumps(body, ensure_ascii=False).encode()


def call_metadata_model(
    parsed: ParsedBook,
    current: BookMetadata,
    settings: Settings,
    *,
    include_cover: bool,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if settings.ai_api_key:
        headers["Authorization"] = f"Bearer {settings.ai_api_key}"
    request = Request(
        f"{settings.ai_base_url.rstrip('/')}/chat/completions",
        data=ai_request_payload(parsed, current, settings, include_cover=include_cover),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=settings.ai_timeout_seconds) as response:
        payload = json.loads(response.read())
    return clean_json_response(payload["choices"][0]["message"]["content"])


def suggest_book_metadata(
    parsed: ParsedBook,
    settings: Settings | None = None,
) -> BookMetadata:
    current_settings = settings or get_settings()
    fallback = fallback_metadata(parsed)
    if (
        current_settings.ai_provider != "openai-compatible"
        or not current_settings.ai_base_url
        or not current_settings.ai_reading_model
    ):
        return fallback

    try:
        payload = call_metadata_model(
            parsed,
            fallback,
            current_settings,
            include_cover=bool(parsed.cover_data_url),
        )
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        if parsed.cover_data_url:
            try:
                payload = call_metadata_model(
                    parsed,
                    fallback,
                    current_settings,
                    include_cover=False,
                )
            except (KeyError, IndexError, TypeError, ValueError, OSError) as retry_exc:
                logger.info("AI metadata extraction unavailable: %s", retry_exc)
                return fallback
        else:
            logger.info("AI metadata extraction unavailable: %s", exc)
            return fallback

    return BookMetadata(
        title=clean_optional_text(payload.get("title"), 300) or fallback.title,
        author=clean_optional_text(payload.get("author"), 200) or fallback.author,
        publisher=clean_optional_text(payload.get("publisher"), 200) or fallback.publisher,
        translator=clean_optional_text(payload.get("translator"), 200) or fallback.translator,
        isbn=clean_optional_text(payload.get("isbn"), 32) or fallback.isbn,
        tags=normalize_book_tags(
            [
                *fallback.tags,
                *(payload.get("tags") if isinstance(payload.get("tags"), list) else []),
            ]
        ),
    )
