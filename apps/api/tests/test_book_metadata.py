import json

from mystery_atlas_api.book_metadata import suggest_book_metadata
from mystery_atlas_api.config import Settings
from mystery_atlas_api.parsers import ParsedBook


def test_ai_preparses_metadata_from_front_matter_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "title": "钟楼谜案",
                                        "author": "林雾",
                                        "publisher": "经纬出版社",
                                        "translator": None,
                                        "isbn": "978-7-1234-5678-9",
                                        "tags": ["本格", "密室"],
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("mystery_atlas_api.book_metadata.urlopen", fake_urlopen)
    settings = Settings(
        _env_file=None,
        ai_base_url="https://ai.example.test/v1",
        ai_api_key="test-key",
        ai_reading_model="metadata-model",
    )
    parsed = ParsedBook(
        title="upload-01",
        chapters=[],
        preview="",
        tags=[],
        metadata_context="目录\n第一章 钟楼\n序章中写有作者林雾。",
        cover_data_url="data:image/png;base64,iVBORw0KGgo=",
    )

    metadata = suggest_book_metadata(parsed, settings)

    assert metadata.title == "钟楼谜案"
    assert metadata.author == "林雾"
    assert metadata.publisher == "经纬出版社"
    assert metadata.isbn == "978-7-1234-5678-9"
    assert metadata.tags == ["本格", "密室"]
    assert captured["timeout"] == 20
    user_content = captured["payload"]["messages"][1]["content"]
    assert user_content[1]["image_url"]["url"] == parsed.cover_data_url
    assert "封面、序章、版权页和目录内容" in user_content[0]["text"]


def test_structured_metadata_is_safe_fallback_without_ai() -> None:
    parsed = ParsedBook(
        title="钟楼谜案",
        chapters=[],
        preview="",
        tags=["本格"],
        author="林雾",
        publisher="经纬出版社",
    )
    settings = Settings(_env_file=None, ai_base_url="", ai_reading_model="")

    metadata = suggest_book_metadata(parsed, settings)

    assert metadata.title == "钟楼谜案"
    assert metadata.author == "林雾"
    assert metadata.publisher == "经纬出版社"
    assert metadata.tags == ["本格"]
