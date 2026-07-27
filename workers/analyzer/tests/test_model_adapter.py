import json
from email.message import Message
from urllib.error import HTTPError

from mystery_atlas_analyzer.contracts import EvidenceAudit
from mystery_atlas_analyzer.model_adapters import OpenAICompatibleAdapter


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
            yield (
                f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n"
            ).encode()
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

    try:
        adapter.generate(
            task="adapter_test",
            system="Return the audit.",
            prompt="No citations.",
            response_model=EvidenceAudit,
            model="kimi-k3",
        )
    except Exception as exc:
        assert "ended before [DONE]" in str(exc)
    else:
        raise AssertionError("an incomplete stream must not be accepted")


def test_truncated_response_retries_with_a_larger_output_budget(monkeypatch) -> None:
    requested_max_tokens: list[int] = []

    class FakeResponse:
        def __init__(self, *, truncated: bool) -> None:
            self.truncated = truncated

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def __iter__(self):
            content = (
                '{"coverage":0'
                if self.truncated
                else json.dumps(
                    {
                        "total_citations": 0,
                        "verified_citations": 0,
                        "unverified_citations": 0,
                        "coverage": 0,
                        "warnings": [],
                    }
                )
            )
            chunk = {
                "choices": [
                    {
                        "delta": {"content": content},
                        "finish_reason": "length" if self.truncated else "stop",
                    }
                ]
            }
            yield f"data: {json.dumps(chunk)}\n".encode()
            yield b"\n"
            yield b"data: [DONE]\n"
            yield b"\n"

    def fake_urlopen(request, timeout):
        del timeout
        requested_max_tokens.append(json.loads(request.data)["max_tokens"])
        return FakeResponse(truncated=len(requested_max_tokens) == 1)

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
        max_output_tokens=8,
        attempts=2,
    )

    result = adapter.generate(
        task="adapter_test",
        system="Return the audit.",
        prompt="No citations.",
        response_model=EvidenceAudit,
        model="deepseek-v4-pro",
    )

    assert result.total_citations == 0
    assert requested_max_tokens == [8, 16]


def test_book_reconciliation_has_a_bounded_output_budget(monkeypatch) -> None:
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
            yield (
                f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n"
            ).encode()
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
        max_output_tokens=32_000,
    )

    adapter.generate(
        task="book_reconciliation",
        system="Return the audit.",
        prompt="No citations.",
        response_model=EvidenceAudit,
        model="deepseek-v4-pro",
    )

    assert captured["payload"]["max_tokens"] == 8_000


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
            yield (
                f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n"
            ).encode()
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
