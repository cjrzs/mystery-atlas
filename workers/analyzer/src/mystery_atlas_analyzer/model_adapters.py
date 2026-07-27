from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from .contracts import ResponseT


class ModelConfigurationError(RuntimeError):
    pass


class ModelResponseError(RuntimeError):
    pass


class ModelOutputTruncatedError(ValueError):
    pass


TASK_OUTPUT_TOKEN_LIMITS = {
    "book_reconciliation": 8_000,
}


def _retry_delay(error: Exception, attempt: int) -> float:
    if isinstance(error, HTTPError) and error.code == 429:
        retry_after = error.headers.get("Retry-After") if error.headers else None
        try:
            requested_delay = float(retry_after) if retry_after is not None else 0
        except ValueError:
            requested_delay = 0
        return min(max(requested_delay, 5 * (2 ** (attempt - 1))), 60)
    return min(2 ** (attempt - 1), 4)


def _read_stream_content(response: Any) -> str:
    content_parts: list[str] = []
    event_data: list[str] = []
    completed = False
    finish_reason: str | None = None

    def process_event() -> bool:
        nonlocal finish_reason
        if not event_data:
            return False
        data = "\n".join(event_data)
        event_data.clear()
        if data == "[DONE]":
            return True
        chunk = json.loads(data)
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return False
        choice = choices[0]
        if not isinstance(choice, dict):
            return False
        current_finish_reason = choice.get("finish_reason")
        if isinstance(current_finish_reason, str):
            finish_reason = current_finish_reason
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            return False
        content = delta.get("content")
        if isinstance(content, str):
            content_parts.append(content)
        return False

    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            if process_event():
                completed = True
                break
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            event_data.append(line[5:].lstrip())
        elif event_data:
            event_data.append(line)

    if not completed and process_event():
        completed = True
    if not completed:
        raise ValueError("model stream ended before [DONE]")
    if finish_reason == "length":
        raise ModelOutputTruncatedError("model response was truncated by max_tokens")
    return "".join(content_parts)


def _extract_json(content: str) -> dict[str, Any]:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        content.strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")
    return payload


@dataclass(frozen=True)
class OpenAICompatibleAdapter:
    base_url: str
    api_key: str = ""
    timeout_seconds: int = 90
    max_output_tokens: int = 8000
    attempts: int = 3

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ModelConfigurationError("MYSTERY_ATLAS_AI_BASE_URL is required")

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def generate(
        self,
        *,
        task: str,
        system: str,
        prompt: str,
        response_model: type[ResponseT],
        model: str,
        temperature: float = 0.1,
    ) -> ResponseT:
        if not model:
            raise ModelConfigurationError(f"no model configured for {task}")

        schema = response_model.model_json_schema()
        repair_context = ""
        last_error: Exception | None = None
        request_max_tokens = min(
            self.max_output_tokens,
            TASK_OUTPUT_TOKEN_LIMITS.get(task, self.max_output_tokens),
        )
        for attempt in range(1, self.attempts + 1):
            normalized_model = model.casefold()
            if normalized_model.startswith("kimi-k3"):
                generation_options: dict[str, Any] = {"reasoning_effort": "low"}
            elif normalized_model.startswith("deepseek-v4"):
                generation_options = {
                    "thinking": {"type": "disabled"},
                    "temperature": temperature,
                }
            else:
                generation_options = {"temperature": temperature}
            body = json.dumps(
                {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f"{system}\nReturn one JSON object only. "
                                f"It must satisfy this JSON Schema:\n"
                                f"{json.dumps(schema, ensure_ascii=False)}"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"<task>{task}</task>\n{prompt}{repair_context}"
                            ),
                        },
                    ],
                    **generation_options,
                    "max_tokens": request_max_tokens,
                    "response_format": {"type": "json_object"},
                    "stream": True,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            request = Request(
                self.endpoint,
                data=body,
                headers=headers,
                method="POST",
            )

            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    content = _read_stream_content(response)
                return response_model.model_validate(_extract_json(content))
            except (
                HTTPError,
                URLError,
                TimeoutError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                ValidationError,
            ) as exc:
                last_error = exc
                if isinstance(exc, ModelOutputTruncatedError):
                    request_max_tokens = min(request_max_tokens * 2, 131_072)
                elif not isinstance(exc, (HTTPError, URLError, TimeoutError)):
                    repair_context = (
                        "\n\nYour previous response was invalid. "
                        "Correct it without commentary. "
                        f"Validation error: {str(exc)[:1200]}"
                    )
                if attempt < self.attempts:
                    time.sleep(_retry_delay(exc, attempt))

        raise ModelResponseError(
            f"{task} failed after {self.attempts} attempts: {last_error}"
        ) from last_error


class StaticModelAdapter:
    """Deterministic adapter for tests and offline pipeline inspection."""

    def __init__(self, responses: dict[str, list[BaseModel] | BaseModel]) -> None:
        self._responses: dict[str, list[BaseModel]] = {}
        for task, value in responses.items():
            self._responses[task] = list(value) if isinstance(value, list) else [value]
        self.calls: list[str] = []

    def generate(
        self,
        *,
        task: str,
        system: str,
        prompt: str,
        response_model: type[ResponseT],
        model: str,
        temperature: float = 0.1,
    ) -> ResponseT:
        del system, prompt, model, temperature
        self.calls.append(task)
        queue = self._responses.get(task, [])
        if not queue:
            raise ModelResponseError(f"no static response configured for {task}")
        value = queue.pop(0)
        return response_model.model_validate(value.model_dump(mode="json"))
