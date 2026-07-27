import json
import os
import zipfile
from pathlib import Path
from uuid import uuid4

from mystery_atlas_api.config import Settings
from mystery_atlas_api.parsers import parse_epub
from mystery_atlas_api.tagging import suggest_book_tags


def write_epub(path: Path, subjects: list[str]) -> None:
    subject_xml = "".join(f"<dc:subject>{subject}</dc:subject>" for subject in subjects)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile full-path="OEBPS/content.opf"
                  media-type="application/oebps-package+xml" />
              </rootfiles>
            </container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="UTF-8"?>
            <package xmlns="http://www.idpf.org/2007/opf"
              xmlns:dc="http://purl.org/dc/elements/1.1/">
              <metadata>
                <dc:title>钟楼谜案</dc:title>
                <dc:creator>林雾</dc:creator>
                <dc:publisher>经纬出版社</dc:publisher>
                <dc:contributor role="trl">周译</dc:contributor>
                <dc:identifier>ISBN 978-7-1234-5678-9</dc:identifier>
                <meta name="cover" content="cover-image" />
                {subject_xml}
              </metadata>
              <manifest>
                <item id="cover-image" href="cover.png"
                  media-type="image/png" properties="cover-image" />
                <item id="chapter-1" href="chapter-1.xhtml"
                  media-type="application/xhtml+xml" />
              </manifest>
              <spine><itemref idref="chapter-1" /></spine>
            </package>""",
        )
        archive.writestr(
            "OEBPS/chapter-1.xhtml",
            "<html><body><h1>第一章</h1><p>所有门窗都从内部锁住了。</p></body></html>",
        )
        archive.writestr("OEBPS/cover.png", b"\x89PNG\r\n\x1a\ncover")


def test_epub_subjects_are_exposed_as_book_tags() -> None:
    path = Path(os.environ["MYSTERY_ATLAS_UPLOAD_DIR"]).parent / f"{uuid4()}.epub"
    write_epub(path, [" 本格 ", "密室", "密室"])

    parsed = parse_epub(path)

    assert parsed.tags == ["本格", "密室"]
    assert parsed.title == "钟楼谜案"
    assert parsed.author == "林雾"
    assert parsed.publisher == "经纬出版社"
    assert parsed.translator == "周译"
    assert parsed.isbn == "978-7-1234-5678-9"
    assert parsed.cover_data_url and parsed.cover_data_url.startswith("data:image/png;base64,")


def test_ai_suggests_tags_when_metadata_has_none(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": '{"tags":["本格","密室","暴风雪山庄"]}'}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers.get("Authorization")
        return FakeResponse()

    monkeypatch.setattr("mystery_atlas_api.tagging.urlopen", fake_urlopen)
    settings = Settings(
        _env_file=None,
        ai_base_url="https://ai.example.test/v1",
        ai_api_key="test-key",
        ai_reading_model="tag-model",
    )

    tags = suggest_book_tags(
        title="钟楼谜案",
        preview="暴风雪封住了山庄，死者房门从内部锁住。",
        settings=settings,
    )

    assert tags == ["本格", "密室", "暴风雪山庄"]
    assert captured == {
        "url": "https://ai.example.test/v1/chat/completions",
        "timeout": 20,
        "authorization": "Bearer test-key",
    }
