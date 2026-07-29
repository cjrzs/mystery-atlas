from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from .contracts import ResponseT

logger = logging.getLogger(__name__)

ADAPTIVE_CONTENT_TASKS = frozenset(
    {
        "chapter_people_relations",
        "chapter_events_evidence",
        "chapter_interpretation",
        "part_synthesis",
        "book_claim_merge",
        "book_claim_audit",
        "book_editorial",
        "book_editorial_structure",
        "book_editorial_interpretation",
        "book_editorial_mysteries",
    }
)


class ModelConfigurationError(RuntimeError):
    pass


class ModelResponseError(RuntimeError):
    pass


class ModelOutputTruncatedError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        response_chars: int = 0,
        finish_reason: str = "length",
    ) -> None:
        super().__init__(message)
        self.response_chars = response_chars
        self.finish_reason = finish_reason


class ModelContentIdleError(TimeoutError):
    def __init__(self, message: str, *, response_chars: int) -> None:
        super().__init__(message)
        self.response_chars = response_chars


@dataclass(frozen=True)
class StreamResult:
    content: str
    finish_reason: str | None
    usage: dict[str, Any]
    first_content_ms: int | None


@dataclass(frozen=True)
class AIRequestProgress:
    call_id: str
    task: str
    model: str
    attempt: int
    response_chars: int
    content_idle_seconds: int


def _retry_delay(error: Exception, attempt: int) -> float:
    if isinstance(error, HTTPError) and error.code == 429:
        retry_after = error.headers.get("Retry-After") if error.headers else None
        try:
            requested_delay = float(retry_after) if retry_after is not None else 0
        except ValueError:
            requested_delay = 0
        return min(max(requested_delay, 5 * (2 ** (attempt - 1))), 60)
    return min(2 ** (attempt - 1), 4)


def _retry_reason(error: Exception) -> str:
    if isinstance(error, HTTPError):
        if error.code == 429:
            return "rate_limit"
        if error.code >= 500:
            return "server_error"
        return "http_client_error"
    if isinstance(error, ModelContentIdleError):
        return "content_idle"
    if isinstance(error, TimeoutError):
        return "network_timeout"
    if isinstance(error, URLError):
        return "network_error"
    if isinstance(error, ModelOutputTruncatedError):
        return "provider_length"
    return "invalid_response"


def _read_stream_content(
    response: Any,
    *,
    content_idle_timeout_seconds: int = 180,
    progress_interval_seconds: int = 15,
    on_progress: Callable[[int, int], None] | None = None,
) -> StreamResult:
    content_parts: list[str] = []
    event_data: list[str] = []
    completed = False
    finish_reason: str | None = None
    usage: dict[str, Any] = {}
    started_at = time.monotonic()
    last_content_at = started_at
    last_progress_at = started_at
    first_content_at: float | None = None
    response_chars = 0

    def process_event(now: float) -> bool:
        nonlocal finish_reason, usage, last_content_at, first_content_at
        nonlocal response_chars
        if not event_data:
            return False
        data = "\n".join(event_data)
        event_data.clear()
        if data == "[DONE]":
            return True
        chunk = json.loads(data)
        current_usage = chunk.get("usage")
        if isinstance(current_usage, dict):
            usage = current_usage
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
            if content:
                response_chars += len(content)
                last_content_at = now
                if first_content_at is None:
                    first_content_at = now
        return False

    for raw_line in response:
        now = time.monotonic()
        if now - last_content_at > content_idle_timeout_seconds:
            raise ModelContentIdleError(
                "model stream produced no effective content before the idle timeout",
                response_chars=sum(len(item) for item in content_parts),
            )
        if (
            on_progress
            and now - last_progress_at >= progress_interval_seconds
        ):
            on_progress(
                response_chars,
                round(now - last_content_at),
            )
            last_progress_at = now
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            if process_event(now):
                completed = True
                break
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            event_data.append(line[5:].lstrip())
        elif event_data:
            event_data.append(line)

    if not completed and process_event(time.monotonic()):
        completed = True
    if not completed:
        raise ValueError("model stream ended before [DONE]")
    if finish_reason == "length":
        raise ModelOutputTruncatedError(
            "model response was truncated by provider",
            response_chars=sum(len(item) for item in content_parts),
            finish_reason=finish_reason,
        )
    return StreamResult(
        content="".join(content_parts),
        finish_reason=finish_reason,
        usage=usage,
        first_content_ms=(
            round((first_content_at - started_at) * 1000)
            if first_content_at is not None
            else None
        ),
    )


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
        raise TypeError("model response must be a JSON object")
    return payload


@dataclass(frozen=True)
class OpenAICompatibleAdapter:
    base_url: str
    api_key: str = ""
    job_id: str = ""
    work_id: str = ""
    edition_id: str = ""
    timeout_seconds: int = 90
    attempts: int = 3
    content_idle_timeout_seconds: int = 180
    progress_interval_seconds: int = 15
    progress_callback: Callable[[AIRequestProgress], None] | None = None

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
        schema_json = json.dumps(schema, ensure_ascii=False)
        repair_context = ""
        last_error: Exception | None = None
        call_id = uuid4().hex[:12]
        for attempt in range(1, self.attempts + 1):
            normalized_model = model.casefold()
            if normalized_model.startswith("kimi-k3"):
                generation_options: dict[str, Any] = {"reasoning_effort": "low"}
                thinking_mode = "low"
            elif normalized_model.startswith("deepseek-v4"):
                generation_options = {
                    "thinking": {"type": "disabled"},
                    "temperature": temperature,
                }
                thinking_mode = "disabled"
            else:
                generation_options = {"temperature": temperature}
                thinking_mode = "default"
            body = json.dumps(
                {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f"{system}\nReturn one JSON object only. "
                                f"It must satisfy this JSON Schema:\n"
                                f"{schema_json}"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (f"<task>{task}</task>\n{prompt}{repair_context}"),
                        },
                    ],
                    **generation_options,
                    "response_format": {"type": "json_object"},
                    "stream": True,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            started_at = time.perf_counter()
            logger.info(
                "AI request started call_id=%s job_id=%s work_id=%s "
                "edition_id=%s task=%s model=%s attempt=%d/%d endpoint=%s "
                "request_bytes=%d prompt_chars=%d schema_chars=%d "
                "max_tokens=unset thinking=%s",
                call_id,
                self.job_id or "unknown",
                self.work_id or "unknown",
                self.edition_id or "unknown",
                task,
                model,
                attempt,
                self.attempts,
                self.endpoint,
                len(body),
                len(prompt),
                len(schema_json),
                thinking_mode,
            )
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
                def report_stream_progress(
                    response_chars: int,
                    content_idle_seconds: int,
                    request_attempt: int = attempt,
                ) -> None:
                    logger.info(
                        "AI request progress call_id=%s task=%s model=%s "
                        "attempt=%d/%d response_chars=%d content_idle_seconds=%d",
                        call_id,
                        task,
                        model,
                        request_attempt,
                        self.attempts,
                        response_chars,
                        content_idle_seconds,
                    )
                    if self.progress_callback:
                        self.progress_callback(
                            AIRequestProgress(
                                call_id=call_id,
                                task=task,
                                model=model,
                                attempt=request_attempt,
                                response_chars=response_chars,
                                content_idle_seconds=content_idle_seconds,
                            )
                        )

                with urlopen(request, timeout=self.timeout_seconds) as response:
                    stream_result = _read_stream_content(
                        response,
                        content_idle_timeout_seconds=(
                            self.content_idle_timeout_seconds
                        ),
                        progress_interval_seconds=(
                            self.progress_interval_seconds
                        ),
                        on_progress=report_stream_progress,
                    )
                content = stream_result.content
                result = response_model.model_validate(_extract_json(content))
                elapsed_ms = round((time.perf_counter() - started_at) * 1000)
                logger.info(
                    "AI request completed call_id=%s task=%s model=%s "
                    "attempt=%d/%d elapsed_ms=%d response_chars=%d "
                    "first_content_ms=%s finish_reason=%s prompt_tokens=%s "
                    "completion_tokens=%s total_tokens=%s",
                    call_id,
                    task,
                    model,
                    attempt,
                    self.attempts,
                    elapsed_ms,
                    len(content),
                    stream_result.first_content_ms
                    if stream_result.first_content_ms is not None
                    else "unknown",
                    stream_result.finish_reason or "unknown",
                    stream_result.usage.get("prompt_tokens", "unknown"),
                    stream_result.usage.get("completion_tokens", "unknown"),
                    stream_result.usage.get("total_tokens", "unknown"),
                )
                return result
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
                elapsed_ms = round((time.perf_counter() - started_at) * 1000)
                truncated = isinstance(exc, ModelOutputTruncatedError)
                content_idle = isinstance(exc, ModelContentIdleError)
                adaptive_content_task = task in ADAPTIVE_CONTENT_TASKS
                if isinstance(exc, HTTPError):
                    retry_limit = (
                        self.attempts
                        if exc.code == 429 or exc.code >= 500
                        else 1
                    )
                elif isinstance(exc, (URLError, TimeoutError)):
                    retry_limit = (
                        1
                        if content_idle and adaptive_content_task
                        else min(self.attempts, 2)
                        if content_idle
                        else self.attempts
                    )
                else:
                    retry_limit = min(self.attempts, 2)
                retry_delay = (
                    _retry_delay(exc, attempt)
                    if (
                        attempt < retry_limit
                        and not truncated
                        and not (content_idle and adaptive_content_task)
                    )
                    else None
                )
                logger.warning(
                    "AI request failed call_id=%s task=%s model=%s "
                    "attempt=%d/%d elapsed_ms=%d error_type=%s "
                    "http_status=%s retry_in_seconds=%s retry_reason=%s "
                    "response_chars=%s finish_reason=%s",
                    call_id,
                    task,
                    model,
                    attempt,
                    self.attempts,
                    elapsed_ms,
                    type(exc).__name__,
                    exc.code if isinstance(exc, HTTPError) else "none",
                    f"{retry_delay:g}" if retry_delay is not None else "none",
                    _retry_reason(exc),
                    getattr(exc, "response_chars", "unknown"),
                    getattr(exc, "finish_reason", "unknown"),
                )
                if truncated or (content_idle and adaptive_content_task):
                    raise
                if not isinstance(exc, (HTTPError, URLError, TimeoutError)):
                    repair_context = (
                        "\n\nYour previous response was invalid. "
                        "Correct it without commentary. "
                        f"Validation error: {str(exc)[:1200]}"
                    )
                if retry_delay is not None:
                    time.sleep(retry_delay)
                else:
                    break

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
