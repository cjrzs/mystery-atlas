import json
import logging
import re
from typing import Any
from urllib.request import Request, urlopen

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


def normalize_book_tags(values: list[Any]) -> list[str]:
    tags: list[str] = []
    for value in values:
        tag = " ".join(str(value).split())
        if tag and len(tag) <= 40 and tag not in tags:
            tags.append(tag)
    return tags[:8]


def parse_tag_response(content: str) -> list[str]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    payload = json.loads(cleaned)
    values = payload.get("tags", []) if isinstance(payload, dict) else []
    return normalize_book_tags(values if isinstance(values, list) else [])


def suggest_book_tags(
    title: str,
    preview: str,
    settings: Settings | None = None,
) -> list[str]:
    current_settings = settings or get_settings()
    if (
        current_settings.ai_provider != "openai-compatible"
        or not current_settings.ai_base_url
        or not current_settings.ai_reading_model
    ):
        return []

    prompt = (
        "你是推理小说档案员。根据书名和正文片段生成 2 到 6 个简短中文书籍标签。"
        "优先描述推理流派、核心诡计类型和叙事类型，例如：本格、密室、时间诡计、"
        "叙述性诡计、社会派、暴风雪山庄。不要输出人物名、书名、剧透或完整句子。"
        '只返回 JSON：{"tags":["标签1","标签2"]}。\n\n'
        f"书名：{title}\n正文片段：{preview[:4000]}"
    )
    body = json.dumps(
        {
            "model": current_settings.ai_reading_model,
            "messages": [
                {"role": "system", "content": "只输出符合要求的 JSON 对象。"},
                {"role": "user", "content": prompt},
            ],
            **(
                {"reasoning_effort": "low"}
                if current_settings.ai_reading_model == "kimi-k3"
                else {"temperature": 0.2}
            ),
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode()
    headers = {"Content-Type": "application/json"}
    if current_settings.ai_api_key:
        headers["Authorization"] = f"Bearer {current_settings.ai_api_key}"
    request = Request(
        f"{current_settings.ai_base_url.rstrip('/')}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=current_settings.ai_timeout_seconds) as response:
            payload = json.loads(response.read())
        content = payload["choices"][0]["message"]["content"]
        return parse_tag_response(content)
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        logger.info("AI tag suggestion unavailable: %s", exc)
        return []
