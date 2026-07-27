import json

from mystery_atlas_api.config import Settings
from mystery_atlas_api.tagging import suggest_book_tags


def test_kimi_k3_uses_supported_request_parameters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"{\\"tags\\":[\\"locked-room\\"]}"}}]}'

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr("mystery_atlas_api.tagging.urlopen", fake_urlopen)
    settings = Settings(
        _env_file=None,
        ai_base_url="https://api.moonshot.ai/v1",
        ai_api_key="test-key",
        ai_reading_model="kimi-k3",
    )

    assert suggest_book_tags("Title", "Preview", settings) == ["locked-room"]
    payload = captured["payload"]
    assert payload["reasoning_effort"] == "low"
    assert "temperature" not in payload
    assert payload["response_format"] == {"type": "json_object"}
