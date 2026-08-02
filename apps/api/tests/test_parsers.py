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


def write_nested_ncx_epub(path: Path) -> None:
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    part_counts = [8, 15, 9]
    manifest = [
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    ]
    spine = []
    resources: dict[str, str] = {}
    nav_points: list[str] = []
    chapter_number = 0
    for part_number, chapter_count in enumerate(part_counts, start=1):
        href = f"part-{part_number}.xhtml"
        item_id = f"part-{part_number}"
        part_title = f"第{part_number}部"
        manifest.append(
            f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{item_id}"/>')
        chapter_html: list[str] = []
        child_points: list[str] = []
        for local_number in range(1, chapter_count + 1):
            chapter_number += 1
            fragment = f"part-{part_number}-chapter-{local_number}"
            chapter_title = f"第{chapter_number}章"
            chapter_html.append(
                f'<h2 id="{fragment}">{chapter_title}</h2>'
                f"<p>正文 {chapter_number}。</p>"
            )
            child_points.append(
                f"""
      <navPoint id="chapter-{chapter_number}" playOrder="{chapter_number + part_number}">
        <navLabel><text>{chapter_title}</text></navLabel>
        <content src="{href}#{fragment}"/>
      </navPoint>"""
            )
        resources[href] = (
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>{part_title}</title></head><body>"
            f"<h1>{part_title}</h1>{''.join(chapter_html)}</body></html>"
        )
        nav_points.append(
            f"""
    <navPoint id="part-{part_number}" playOrder="{part_number}">
      <navLabel><text>{part_title}</text></navLabel>
      <content src="{href}"/>
      {''.join(child_points)}
    </navPoint>"""
        )

    package = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"
  unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">fixture-nested-ncx</dc:identifier>
    <dc:title>Nested NCX Mystery</dc:title>
    <dc:creator>Fixture Author</dc:creator>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>{''.join(manifest)}</manifest>
  <spine toc="ncx">{''.join(spine)}</spine>
</package>
"""
    ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:depth" content="2"/></head>
  <docTitle><text>Nested NCX Mystery</text></docTitle>
  <navMap>{''.join(nav_points)}</navMap>
</ncx>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        archive.writestr("OEBPS/toc.ncx", ncx)
        for href, html in resources.items():
            archive.writestr(f"OEBPS/{href}", html)


def write_split_title_body_ncx_epub(path: Path) -> None:
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    package = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Split Story Collection</dc:title>
    <dc:creator>Fixture Author</dc:creator>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="title-page" href="title-page.xhtml" media-type="application/xhtml+xml"/>
    <item id="title-1" href="title-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="body-1" href="body-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="title-2" href="title-2.xhtml" media-type="application/xhtml+xml"/>
    <item id="body-2" href="body-2.xhtml" media-type="application/xhtml+xml"/>
    <item id="promo" href="promo.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="title-page"/>
    <itemref idref="title-1"/>
    <itemref idref="body-1"/>
    <itemref idref="title-2"/>
    <itemref idref="body-2"/>
    <itemref idref="promo"/>
  </spine>
</package>
"""
    ncx = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <docTitle><text>Split Story Collection</text></docTitle>
  <navMap>
    <navPoint id="title-page" playOrder="1">
      <navLabel><text>书名页</text></navLabel>
      <content src="title-page.xhtml"/>
    </navPoint>
    <navPoint id="story-1" playOrder="2">
      <navLabel><text>Story One</text></navLabel>
      <content src="title-1.xhtml"/>
    </navPoint>
    <navPoint id="story-2" playOrder="3">
      <navLabel><text>Story Two</text></navLabel>
      <content src="title-2.xhtml"/>
    </navPoint>
  </navMap>
</ncx>
"""
    documents = {
        "title-page.xhtml": "<html><head><title>Collection</title></head>"
        "<body><p>书名页</p><p>Fixture Author</p></body></html>",
        "title-1.xhtml": "<html><head><title>Collection</title></head>"
        "<body><p>Story One</p></body></html>",
        "body-1.xhtml": "<html><head><title>Collection</title></head>"
        "<body><p>The first story body is here.</p></body></html>",
        "title-2.xhtml": "<html><head><title>Collection</title></head>"
        "<body><p>Story Two</p><p>A case note.</p></body></html>",
        "body-2.xhtml": "<html><head><title>Collection</title></head>"
        "<body><p>The second story body is here.</p></body></html>",
        "promo.xhtml": "<html><head><title>Other Book</title></head>"
        "<body><p>Promotional material must stay outside the last story.</p></body></html>",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        archive.writestr("OEBPS/toc.ncx", ncx)
        for href, html in documents.items():
            archive.writestr(f"OEBPS/{href}", html)


def write_epub3_nav_epub(
    path: Path,
    *,
    broken_targets: bool = False,
    oversized: bool = False,
) -> None:
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="EPUB/package.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    package = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>EPUB 3 Fixture</dc:title>
    <dc:creator>Fixture Author</dc:creator>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="part" href="part.xhtml" media-type="application/xhtml+xml"/>
    <item id="image" href="images/clue.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="part"/></spine>
</package>
"""
    first_target = "missing-one" if broken_targets else "chapter-one"
    second_target = "missing-two" if broken_targets else "chapter-two"
    nav = f"""<html xmlns="http://www.w3.org/1999/xhtml"
  xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Contents</title></head><body>
    <nav epub:type="toc"><ol>
      <li><a href="part.xhtml#part-one">Part One</a><ol>
        <li><a href="part.xhtml#{first_target}">Chapter One</a></li>
        <li><a href="part.xhtml#{second_target}">Chapter Two</a></li>
      </ol></li>
    </ol></nav>
  </body>
</html>"""
    first_body = "A" * 50_100 if oversized else "The first clue appears."
    content = f"""<html xmlns="http://www.w3.org/1999/xhtml"
  xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Part One</title></head><body>
    <h1 id="part-one">Part One</h1>
    <h2 id="chapter-one">Chapter One</h2>
    <p id="paragraph-one">{first_body} <a href="#note-one" epub:type="noteref">1</a></p>
    <img id="clue-image" src="images/clue.png" alt="Clue map"/>
    <aside id="note-one" epub:type="footnote"><p>The footnote secret.</p></aside>
    <h2 id="chapter-two">Chapter Two</h2><p>The case continues.</p>
  </body>
</html>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("EPUB/package.opf", package)
        archive.writestr("EPUB/nav.xhtml", nav)
        archive.writestr("EPUB/part.xhtml", content)
        archive.writestr("EPUB/images/clue.png", b"fixture")


def test_epub_parser_uses_nested_ncx_leaf_chapters(
    local_tmp_path: Path,
) -> None:
    path = local_tmp_path / "nested-ncx.epub"
    write_nested_ncx_epub(path)

    parsed = parse_epub(path)

    assert len(parsed.chapters) == 32
    assert [chapter["title"] for chapter in parsed.chapters[:2]] == [
        "第1章",
        "第2章",
    ]
    assert parsed.chapters[0]["structural_path"] == ["第1部", "第1章"]
    assert parsed.chapters[8]["structural_path"] == ["第2部", "第9章"]
    assert parsed.chapters[-1]["structural_path"] == ["第3部", "第32章"]
    assert parsed.chapters[0]["source_locator"] == {
        "format": "epub",
        "resource": "OEBPS/part-1.xhtml",
        "fragment": "part-1-chapter-1",
        "spine_index": 0,
    }
    assert parsed.chapters[0]["text"] == "正文 1。"
    assert parsed.chapters[0]["structure_source"] == "epub_ncx"
    assert parsed.chapters[0]["structure_confidence"] == "high"


def test_epub_parser_merges_body_after_separate_ncx_title_page(
    local_tmp_path: Path,
) -> None:
    path = local_tmp_path / "split-title-body-ncx.epub"
    write_split_title_body_ncx_epub(path)

    parsed = parse_epub(path)

    assert parsed.parser_version == "epub-structure-v2"
    assert [chapter["title"] for chapter in parsed.chapters] == [
        "Story One",
        "Story Two",
    ]
    assert parsed.chapters[0]["text"] == "The first story body is here."
    assert parsed.chapters[1]["text"] == (
        "A case note.\n\nThe second story body is here."
    )
    assert "Promotional material" not in parsed.chapters[1]["text"]
    assert parsed.chapters[0]["source_locator"] == {
        "format": "epub",
        "resource": "OEBPS/title-1.xhtml",
        "fragment": "",
        "spine_index": 1,
    }


def test_epub3_nav_preserves_nested_structure_and_reader_semantics(
    local_tmp_path: Path,
) -> None:
    path = local_tmp_path / "epub3-nav.epub"
    write_epub3_nav_epub(path)

    parsed = parse_epub(path)

    assert parsed.structure_source == "epub_nav"
    assert parsed.structure_confidence == "high"
    assert [chapter["structural_path"] for chapter in parsed.chapters] == [
        ["Part One", "Chapter One"],
        ["Part One", "Chapter Two"],
    ]
    first = parsed.chapters[0]
    assert "The footnote secret." not in first["text"]
    paragraph = next(block for block in first["blocks"] if block["type"] == "paragraph")
    assert paragraph["anchors"] == ["paragraph-one"]
    assert paragraph["links"] == [
        {"href": "#note-one", "semantic_type": "noteref", "text": "1"}
    ]
    figure = next(block for block in first["blocks"] if block["type"] == "figure")
    assert figure["alt"] == "Clue map"
    assert figure["resource"] == "EPUB/images/clue.png"


def test_epub3_broken_nav_falls_back_to_content_heading_hierarchy(
    local_tmp_path: Path,
) -> None:
    path = local_tmp_path / "epub3-broken-nav.epub"
    write_epub3_nav_epub(path, broken_targets=True)

    parsed = parse_epub(path)

    assert parsed.structure_source == "content_headings"
    assert parsed.structure_confidence == "medium"
    assert [chapter["title"] for chapter in parsed.chapters] == [
        "Chapter One",
        "Chapter Two",
    ]


def test_obviously_oversized_epub_chapter_waits_for_structure_review(
    local_tmp_path: Path,
) -> None:
    path = local_tmp_path / "epub3-oversized.epub"
    write_epub3_nav_epub(path, oversized=True)

    parsed = parse_epub(path)

    assert parsed.structure_requires_review is True
    assert parsed.structure_confidence == "low"
    assert any("异常偏长章节" in warning for warning in parsed.structure_warnings)


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
