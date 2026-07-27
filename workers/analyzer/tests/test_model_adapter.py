import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from mystery_atlas_analyzer import model_adapters
from mystery_atlas_analyzer.contracts import EvidenceAudit
from mystery_atlas_analyzer.model_adapters import (
    ModelOutputTruncatedError,
    ModelResponseError,
    OpenAICompatibleAdapter,
)


def test_sse_heartbeats_do_not_reset_the_effective_content_idle_timeout(
    monkeypatch,
) -> None:
    class HeartbeatsOnly:
        def __iter__(self):
            yield b": keep-alive\n"
            yield b": keep-alive\n"

    monotonic_times = iter([0.0, 10.0, 181.0])
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.monotonic",
        lambda: next(monotonic_times),
    )

    assert hasattr(model_adapters, "ModelContentIdleError")
    with pytest.raises(model_adapters.ModelContentIdleError) as caught:
        model_adapters._read_stream_content(
            HeartbeatsOnly(),
            content_idle_timeout_seconds=180,
        )

    assert caught.value.response_chars == 0


def test_kimi_k3_request_uses_reasoning_effort(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            content = json.dumps(
                {
                    "total_citations": 0,
                    "verified_citations": 0,
                    "unverified_citations": 0,
                    "coverage": 0,
                    "warnings": [],
                }
            )
            midpoint = len(content) // 2
            for part in (content[:midpoint], content[midpoint:]):
                chunk = {
                    "choices": [
                        {
                            "delta": {"content": part},
                            "finish_reason": None,
                        }
                    ]
                }
                yield f"data: {json.dumps(chunk)}\n".encode()
                yield b"\n"
            yield b"data: [DONE]\n"
            yield b"\n"

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        fake_urlopen,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.moonshot.ai/v1",
        api_key="test-key",
        timeout_seconds=42,
    )

    result = adapter.generate(
        task="adapter_test",
        system="Return the audit.",
        prompt="No citations.",
        response_model=EvidenceAudit,
        model="kimi-k3",
    )

    assert result.total_citations == 0
    assert captured["timeout"] == 42
    payload = captured["payload"]
    assert payload["reasoning_effort"] == "low"
    assert "temperature" not in payload
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is True


def test_deepseek_v4_request_disables_thinking_for_bulk_json(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            content = json.dumps(
                {
                    "total_citations": 0,
                    "verified_citations": 0,
                    "unverified_citations": 0,
                    "coverage": 0,
                    "warnings": [],
                }
            )
            yield (f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n").encode()
            yield b"\n"
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout):
        del timeout
        captured["payload"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        fake_urlopen,
    )
    adapter = OpenAICompatibleAdapter(base_url="https://api.deepseek.com/v1")

    adapter.generate(
        task="adapter_test",
        system="Return the audit.",
        prompt="No citations.",
        response_model=EvidenceAudit,
        model="deepseek-v4-pro",
    )

    payload = captured["payload"]
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["temperature"] == 0.1


def test_successful_request_logs_safe_timing_and_size_metadata(
    monkeypatch,
    caplog,
) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            content = json.dumps(
                {
                    "total_citations": 0,
                    "verified_citations": 0,
                    "unverified_citations": 0,
                    "coverage": 0,
                    "warnings": ["sensitive model output"],
                }
            )
            yield (f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n").encode()
            yield b"\n"
            yield b"data: [DONE]\n\n"

    monotonic_times = iter([10.0, 10.125])
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.perf_counter",
        lambda: next(monotonic_times),
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example.test/v1",
        api_key="sensitive-api-key",
        job_id="job-123",
        work_id="work-123",
        edition_id="edition-123",
    )

    with caplog.at_level(
        "INFO",
        logger="mystery_atlas_analyzer.model_adapters",
    ):
        adapter.generate(
            task="segment_analysis",
            system="Return the audit.",
            prompt="sensitive source text",
            response_model=EvidenceAudit,
            model="deepseek-v4-pro",
        )

    started = next(
        record.getMessage()
        for record in caplog.records
        if "AI request started" in record.getMessage()
    )
    completed = next(
        record.getMessage()
        for record in caplog.records
        if "AI request completed" in record.getMessage()
    )
    assert "call_id=" in started
    assert "task=segment_analysis" in started
    assert "job_id=job-123" in started
    assert "work_id=work-123" in started
    assert "edition_id=edition-123" in started
    assert "model=deepseek-v4-pro" in started
    assert "attempt=1/3" in started
    assert "endpoint=https://api.example.test/v1/chat/completions" in started
    assert "request_bytes=" in started
    assert "prompt_chars=" in started
    assert "schema_chars=" in started
    assert "max_tokens=unset" in started
    assert "thinking=disabled" in started
    assert "elapsed_ms=125" in completed
    assert "response_chars=" in completed
    assert "sensitive-api-key" not in caplog.text
    assert "sensitive source text" not in caplog.text
    assert "sensitive model output" not in caplog.text


def test_successful_request_logs_finish_reason_and_provider_usage(
    monkeypatch,
    caplog,
) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            content = json.dumps(
                {
                    "total_citations": 0,
                    "verified_citations": 0,
                    "unverified_citations": 0,
                    "coverage": 0,
                    "warnings": [],
                }
            )
            chunk = {
                "choices": [
                    {
                        "delta": {"content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "total_tokens": 168,
                },
            }
            yield f"data: {json.dumps(chunk)}\n".encode()
            yield b"\n"
            yield b"data: [DONE]\n\n"

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    adapter = OpenAICompatibleAdapter(base_url="https://api.example.test/v1")

    with caplog.at_level(
        "INFO",
        logger="mystery_atlas_analyzer.model_adapters",
    ):
        adapter.generate(
            task="book_editorial",
            system="Return the audit.",
            prompt="Compact facts.",
            response_model=EvidenceAudit,
            model="deepseek-v4-pro",
        )

    completed = next(
        record.getMessage()
        for record in caplog.records
        if "AI request completed" in record.getMessage()
    )
    assert "finish_reason=stop" in completed
    assert "prompt_tokens=123" in completed
    assert "completion_tokens=45" in completed
    assert "total_tokens=168" in completed
    assert "first_content_ms=" in completed


def test_stream_progress_callback_reports_sizes_without_exposing_content(
    monkeypatch,
) -> None:
    sensitive_content = json.dumps(
        {
            "total_citations": 0,
            "verified_citations": 0,
            "unverified_citations": 0,
            "coverage": 0,
            "warnings": ["private"],
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            chunk = {
                "choices": [
                    {
                        "delta": {"content": sensitive_content},
                        "finish_reason": None,
                    }
                ]
            }
            yield f"data: {json.dumps(chunk)}\n".encode()
            yield b"\n"
            yield b": keep-alive\n"
            yield b"data: [DONE]\n"
            yield b"\n"

    monotonic_times = iter([0.0, 1.0, 2.0, 17.0, 18.0, 19.0])
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.monotonic",
        lambda: next(monotonic_times),
    )
    updates: list[object] = []
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example.test/v1",
        progress_interval_seconds=15,
        progress_callback=updates.append,
    )

    adapter.generate(
        task="book_editorial",
        system="Return the audit.",
        prompt="Compact facts.",
        response_model=EvidenceAudit,
        model="deepseek-v4-pro",
    )

    assert len(updates) == 1
    update = updates[0]
    assert update.task == "book_editorial"
    assert update.response_chars == len(sensitive_content)
    assert update.content_idle_seconds == 15
    assert sensitive_content not in repr(update)


def test_failed_attempt_logs_http_status_and_retry_delay(
    monkeypatch,
    caplog,
) -> None:
    calls = 0
    sleeps: list[float] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            content = json.dumps(
                {
                    "total_citations": 0,
                    "verified_citations": 0,
                    "unverified_citations": 0,
                    "coverage": 0,
                    "warnings": [],
                }
            )
            yield (f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n").encode()
            yield b"\n"
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout):
        del request, timeout
        nonlocal calls
        calls += 1
        if calls == 1:
            headers = Message()
            headers["Retry-After"] = "5"
            raise HTTPError(
                "https://api.example.test/chat/completions",
                429,
                "Too Many Requests",
                headers,
                None,
            )
        return FakeResponse()

    monotonic_times = iter([20.0, 20.05, 21.0, 21.25])
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.sleep",
        sleeps.append,
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.perf_counter",
        lambda: next(monotonic_times),
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example.test/v1",
        attempts=2,
    )

    with caplog.at_level(
        "INFO",
        logger="mystery_atlas_analyzer.model_adapters",
    ):
        adapter.generate(
            task="segment_analysis",
            system="Return the audit.",
            prompt="No citations.",
            response_model=EvidenceAudit,
            model="deepseek-v4-pro",
        )

    started = [
        record.getMessage()
        for record in caplog.records
        if "AI request started" in record.getMessage()
    ]
    failed = next(
        record.getMessage()
        for record in caplog.records
        if "AI request failed" in record.getMessage()
    )
    completed = next(
        record.getMessage()
        for record in caplog.records
        if "AI request completed" in record.getMessage()
    )
    assert len(started) == 2
    assert "attempt=1/2" in started[0]
    assert "attempt=2/2" in started[1]
    assert "attempt=1/2" in failed
    assert "elapsed_ms=50" in failed
    assert "error_type=HTTPError" in failed
    assert "http_status=429" in failed
    assert "retry_in_seconds=5" in failed
    assert "retry_reason=rate_limit" in failed
    assert "attempt=2/2" in completed
    assert sleeps == [5.0]


def test_invalid_json_gets_only_one_repair_attempt(monkeypatch) -> None:
    calls = 0

    class InvalidResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"not-json"}}]}\n'
            yield b"\n"
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout):
        del request, timeout
        nonlocal calls
        calls += 1
        return InvalidResponse()

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.sleep",
        lambda delay: None,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example.test/v1",
        attempts=3,
    )

    with pytest.raises(model_adapters.ModelResponseError):
        adapter.generate(
            task="book_editorial",
            system="Return the audit.",
            prompt="Compact facts.",
            response_model=EvidenceAudit,
            model="deepseek-v4-pro",
        )

    assert calls == 2


def test_non_splittable_content_idle_retries_only_once(monkeypatch) -> None:
    calls = 0
    content = json.dumps(
        {
            "total_citations": 0,
            "verified_citations": 0,
            "unverified_citations": 0,
            "coverage": 0,
            "warnings": [],
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_read_stream(response, **kwargs):
        del response, kwargs
        nonlocal calls
        calls += 1
        if calls == 1:
            raise model_adapters.ModelContentIdleError(
                "idle",
                response_chars=0,
            )
        return model_adapters.StreamResult(
            content=content,
            finish_reason="stop",
            usage={},
            first_content_ms=10,
        )

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters._read_stream_content",
        fake_read_stream,
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.sleep",
        lambda delay: None,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example.test/v1",
        attempts=3,
    )

    result = adapter.generate(
        task="segment_analysis",
        system="Return the audit.",
        prompt="Source segment.",
        response_model=EvidenceAudit,
        model="deepseek-v4-pro",
    )

    assert result.total_citations == 0
    assert calls == 2


def test_incomplete_stream_is_rejected(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"{\\"coverage\\":0"}}]}\n'
            yield b"\n"

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.moonshot.cn/v1",
        api_key="test-key",
        attempts=1,
    )

    with pytest.raises(ModelResponseError, match=r"ended before \[DONE\]"):
        adapter.generate(
            task="adapter_test",
            system="Return the audit.",
            prompt="No citations.",
            response_model=EvidenceAudit,
            model="kimi-k3",
        )


def test_provider_truncation_fails_without_repeating_the_same_request(
    monkeypatch,
    caplog,
) -> None:
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            chunk = {
                "choices": [
                    {
                        "delta": {"content": '{"coverage":0'},
                        "finish_reason": "length",
                    }
                ]
            }
            yield f"data: {json.dumps(chunk)}\n".encode()
            yield b"\n"
            yield b"data: [DONE]\n"
            yield b"\n"

    def fake_urlopen(request, timeout):
        del request, timeout
        nonlocal calls
        calls += 1
        return FakeResponse()

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.sleep",
        lambda delay: None,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example.test/v1",
        attempts=3,
    )

    with caplog.at_level(
        "WARNING",
        logger="mystery_atlas_analyzer.model_adapters",
    ), pytest.raises(ModelOutputTruncatedError) as caught:
        adapter.generate(
            task="adapter_test",
            system="Return the audit.",
            prompt="No citations.",
            response_model=EvidenceAudit,
            model="deepseek-v4-pro",
        )

    assert calls == 1
    assert caught.value.response_chars == len('{"coverage":0')
    assert caught.value.finish_reason == "length"
    failed = next(
        record.getMessage()
        for record in caplog.records
        if "AI request failed" in record.getMessage()
    )
    assert "response_chars=13" in failed
    assert "finish_reason=length" in failed


def test_book_analysis_request_does_not_set_max_tokens(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            content = json.dumps(
                {
                    "total_citations": 0,
                    "verified_citations": 0,
                    "unverified_citations": 0,
                    "coverage": 0,
                    "warnings": [],
                }
            )
            yield (f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n").encode()
            yield b"\n"
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout):
        del timeout
        captured["payload"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        fake_urlopen,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.deepseek.com/v1",
        api_key="test-key",
    )

    adapter.generate(
        task="book_reconciliation",
        system="Return the audit.",
        prompt="No citations.",
        response_model=EvidenceAudit,
        model="deepseek-v4-pro",
    )

    assert "max_tokens" not in captured["payload"]


def test_rate_limit_retry_honors_retry_after(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            content = json.dumps(
                {
                    "total_citations": 0,
                    "verified_citations": 0,
                    "unverified_citations": 0,
                    "coverage": 0,
                    "warnings": [],
                }
            )
            yield (f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n").encode()
            yield b"\n"
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout):
        del request, timeout
        nonlocal calls
        calls += 1
        if calls == 1:
            headers = Message()
            headers["Retry-After"] = "5"
            raise HTTPError(
                "https://api.example.test/chat/completions",
                429,
                "Too Many Requests",
                headers,
                None,
            )
        return FakeResponse()

    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "mystery_atlas_analyzer.model_adapters.time.sleep",
        sleeps.append,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example.test/v1",
        attempts=2,
    )

    result = adapter.generate(
        task="adapter_test",
        system="Return the audit.",
        prompt="No citations.",
        response_model=EvidenceAudit,
        model="kimi-k3",
    )

    assert result.total_citations == 0
    assert sleeps == [5.0]
