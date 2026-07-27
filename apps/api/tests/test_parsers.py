import tempfile
import zipfile
from pathlib import Path

import pytest

from mystery_atlas_api.parsers import (
    parse_epub,
    select_mainline_chapters,
    split_text_chapters,
    text_to_blocks,
)


@pytest.fixture
def local_tmp_path() -> Path:
    root = Path.cwd() / ".test-tmp"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, ignore_cleanup_errors=True) as path:
        yield Path(path)


def write_epub(path: Path) -> None:
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    items = [
        ("toc", "toc.xhtml", "Contents", "Table of Contents"),
        ("author", "author.xhtml", "作者介绍", "A biography outside the novel."),
        ("prologue", "prologue.xhtml", "序章", "A story prologue that is not mainline."),
        ("chapter-1", "chapter-1.xhtml", "第一章 英国", "The novel begins here."),
        ("chapter-2", "chapter-2.xhtml", "第二章", "The investigation continues."),
        ("end-toc", "end-toc.xhtml", "Table of Contents", "Chapter links."),
    ]
    manifest = "\n".join(
        f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>'
        for item_id, href, _, _ in items
    )
    spine = "\n".join(f'<itemref idref="{item_id}"/>' for item_id, *_ in items)
    package = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fixture Mystery</dc:title>
    <dc:creator>Fixture Author</dc:creator>
  </metadata>
  <manifest>{manifest}</manifest>
  <spine>{spine}</spine>
</package>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        for _, href, title, body in items:
            archive.writestr(
                f"OEBPS/{href}",
                (
                    '<html xmlns="http://www.w3.org/1999/xhtml">'
                    f"<head><title>{title}</title></head>"
                    f"<body><h1>{title}</h1><p>{body}</p></body></html>"
                ),
            )


def test_epub_parser_keeps_only_numbered_mainline_chapters(
    local_tmp_path: Path,
) -> None:
    path = local_tmp_path / "fixture.epub"
    write_epub(path)

    parsed = parse_epub(path)

    assert [chapter["number"] for chapter in parsed.chapters] == [1, 2]
    assert [chapter["title"] for chapter in parsed.chapters] == [
        "第一章 英国",
        "第二章",
    ]
    assert [chapter["source_locator"]["resource"] for chapter in parsed.chapters] == [
        "OEBPS/chapter-1.xhtml",
        "OEBPS/chapter-2.xhtml",
    ]


def test_untitled_single_section_does_not_get_a_system_chapter_name() -> None:
    chapters = split_text_chapters("The source has no explicit chapter heading.")

    assert len(chapters) == 1
    assert chapters[0]["title"] == ""


def test_named_story_chapter_is_not_mistaken_for_cover_material() -> None:
    chapters = select_mainline_chapters(
        [{"number": 1, "title": "Discovery", "text": "A clue is discovered."}]
    )

    assert [chapter["title"] for chapter in chapters] == ["Discovery"]


def test_epub_reader_blocks_preserve_paragraphs_breaks_and_quotes(
    local_tmp_path: Path,
) -> None:
    path = local_tmp_path / "semantic.epub"
    write_epub(path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            "OEBPS/chapter-1.xhtml",
            (
                '<html xmlns="http://www.w3.org/1999/xhtml">'
                "<head><title>第一章 英国</title></head><body>"
                "<h1>第一章 英国</h1>"
                "<p>第一段。<br/>仍在第一段。</p>"
                "<blockquote>一段引文。</blockquote>"
                "<hr/><p>第二段。</p>"
                "</body></html>"
            ),
        )

    parsed = parse_epub(path)
    blocks = parsed.chapters[0]["blocks"]

    assert blocks == [
        {"type": "paragraph", "text": "第一段。\n仍在第一段。"},
        {"type": "quote", "text": "一段引文。"},
        {"type": "divider", "text": ""},
        {"type": "paragraph", "text": "第二段。"},
    ]


def test_chinese_txt_single_line_breaks_become_paragraphs() -> None:
    blocks = text_to_blocks("第一段。\n第二段。", source_format="txt")

    assert blocks == [
        {"type": "paragraph", "text": "第一段。"},
        {"type": "paragraph", "text": "第二段。"},
    ]
