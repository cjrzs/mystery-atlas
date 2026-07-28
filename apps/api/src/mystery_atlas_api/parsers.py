import base64
import hashlib
import json
import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree

from pypdf import PdfReader

CHAPTER_PATTERN = re.compile(
    r"(?m)^\s*((?:第[0-9一二三四五六七八九十百千零〇两]+[章节回卷部篇]|"
    r"Chapter\s+[0-9IVXLC]+)[^\n]{0,80})\s*$",
    re.IGNORECASE,
)
NON_MAINLINE_EXACT_TITLES = {
    "cover",
    "titlepage",
    "content",
    "contents",
    "tableofcontents",
    "copyright",
    "colophon",
    "abouttheauthor",
    "authorintroduction",
    "authorbiography",
    "chronology",
    "preface",
    "foreword",
    "prologue",
    "epilogue",
    "acknowledgment",
    "acknowledgments",
    "acknowledgement",
    "acknowledgements",
    "appendix",
    "封面",
    "扉页",
    "目录",
    "版权",
    "出版说明",
    "作者介绍",
    "作者简介",
    "出版前言",
    "前言",
    "序言",
    "序章",
    "楔子",
    "尾声",
    "后记",
    "跋",
    "附录",
    "献词",
    "致谢",
}
NON_MAINLINE_TITLE_FRAGMENTS = (
    "作品年表",
    "侦探作品年表",
    "作者简介",
    "作者介绍",
    "版权信息",
    "推荐",
)
ZERO_CHAPTER_PATTERN = re.compile(
    r"^(?:第[零〇0]章|Chapter\s+(?:0|Zero))",
    re.IGNORECASE,
)
BLOCK_TAG_TYPES = {
    "p": "paragraph",
    "div": "paragraph",
    "section": "paragraph",
    "article": "paragraph",
    "aside": "paragraph",
    "li": "paragraph",
    "blockquote": "quote",
    "pre": "pre",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
}
DIVIDER_PATTERN = re.compile(r"^\s*(?:[-—_=·*#]\s*){3,}$")
CHINESE_CHARACTER_PATTERN = re.compile(r"[\u3400-\u9fff]")
EPUB_PARSER_VERSION = "epub-structure-v1"
NOTE_SEMANTICS = {"footnote", "endnote", "rearnote"}
NON_MAINLINE_SEMANTICS = {
    "cover",
    "titlepage",
    "toc",
    "copyright-page",
    "acknowledgments",
    "bibliography",
    "colophon",
    "index",
}


@dataclass
class ParsedBook:
    title: str
    chapters: list[dict]
    preview: str
    tags: list[str]
    author: str | None = None
    publisher: str | None = None
    translator: str | None = None
    isbn: str | None = None
    language: str | None = None
    metadata_context: str = ""
    cover_data_url: str | None = None
    structure_version: str = ""
    structure_source: str = ""
    structure_confidence: str = "low"
    structure_warnings: list[str] | None = None
    structure: list[dict] | None = None
    structure_requires_review: bool = False
    parser_version: str = ""
    metadata: dict | None = None


class HtmlTextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[dict] = []
        self.block_parts: list[str] = []
        self.block_type = "paragraph"
        self.block_meta: dict[str, object] = {}
        self.title_parts: list[str] = []
        self.open_tags: list[str] = []
        self.tag_semantics: list[set[str]] = []
        self.active_links: list[dict[str, object]] = []
        self.anchors: dict[str, int] = {}
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        current_tag = tag.lower()
        attr_map = {
            name.rsplit(":", 1)[-1].lower(): value or ""
            for name, value in attrs
        }
        semantics = {
            token.casefold()
            for token in re.split(r"\s+", attr_map.get("type", ""))
            if token
        }
        self.open_tags.append(current_tag)
        self.tag_semantics.append(semantics)
        if current_tag in {"script", "style", "nav"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if current_tag in BLOCK_TAG_TYPES:
            self.flush_block()
            self.block_type = BLOCK_TAG_TYPES[current_tag]
            if current_tag.startswith("h") and current_tag[1:].isdigit():
                self.block_meta["level"] = int(current_tag[1:])
            self._attach_semantics()
            self._attach_anchor(attr_map)
        elif current_tag == "br":
            self.block_parts.append("\n")
        elif current_tag == "hr":
            self.flush_block()
            self.blocks.append({"type": "divider", "text": ""})
        elif current_tag == "img":
            self.flush_block()
            image: dict[str, object] = {
                "type": "figure",
                "text": attr_map.get("alt") or attr_map.get("title") or "",
                "src": attr_map.get("src", ""),
                "alt": attr_map.get("alt", ""),
            }
            semantic_type = self._current_semantic_type()
            if semantic_type:
                image["semantic_type"] = semantic_type
            if attr_map.get("id"):
                image["id"] = attr_map["id"]
                self.anchors[attr_map["id"]] = len(self.blocks)
            self.blocks.append(image)
        elif current_tag == "a":
            self._attach_anchor(attr_map)
            self.active_links.append(
                {
                    "href": attr_map.get("href", ""),
                    "semantic_type": " ".join(sorted(semantics)),
                    "text_parts": [],
                }
            )
        else:
            self._attach_anchor(attr_map)
            if "pagebreak" in semantics:
                self.flush_block()
                marker: dict[str, object] = {
                    "type": "pagebreak",
                    "text": attr_map.get("title") or attr_map.get("label") or "",
                }
                if attr_map.get("id"):
                    marker["id"] = attr_map["id"]
                    self.anchors[attr_map["id"]] = len(self.blocks)
                self.blocks.append(marker)

    def handle_endtag(self, tag: str) -> None:
        current_tag = tag.lower()
        if current_tag in {"script", "style", "nav"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and current_tag in BLOCK_TAG_TYPES:
            self.flush_block()
        elif not self.ignored_depth and current_tag == "a" and self.active_links:
            link = self.active_links.pop()
            text_value = " ".join(
                "".join(link.pop("text_parts", [])).split()
            )
            if text_value:
                link["text"] = text_value
            links = self.block_meta.setdefault("links", [])
            assert isinstance(links, list)
            links.append({key: value for key, value in link.items() if value})
        for index in range(len(self.open_tags) - 1, -1, -1):
            if self.open_tags[index] == current_tag:
                del self.open_tags[index]
                del self.tag_semantics[index]
                break

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        if not data or not data.strip():
            return
        if "title" in self.open_tags:
            if len("".join(self.title_parts)) < 160:
                self.title_parts.append(data)
            return
        self.block_parts.append(data)
        for link in self.active_links:
            parts = link.get("text_parts")
            if isinstance(parts, list):
                parts.append(data)

    def close(self) -> None:
        super().close()
        self.flush_block()

    def flush_block(self) -> None:
        raw = "".join(self.block_parts)
        self.block_parts = []
        if self.block_type == "pre":
            value = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
        else:
            value = re.sub(r"[^\S\n]+", " ", raw)
            value = re.sub(r" *\n *", "\n", value).strip()
        if value:
            block: dict[str, object] = {"type": self.block_type, "text": value}
            block.update(self.block_meta)
            self.blocks.append(block)
        self.block_type = "paragraph"
        self.block_meta = {}

    def _current_semantic_type(self) -> str:
        values = {
            value
            for scope in self.tag_semantics
            for value in scope
        }
        return " ".join(sorted(values))

    def _attach_semantics(self) -> None:
        semantic_type = self._current_semantic_type()
        if semantic_type:
            self.block_meta["semantic_type"] = semantic_type

    def _attach_anchor(self, attrs: dict[str, str]) -> None:
        anchor = attrs.get("id") or attrs.get("name")
        if not anchor:
            return
        self.anchors[anchor] = len(self.blocks)
        anchors = self.block_meta.setdefault("anchors", [])
        assert isinstance(anchors, list)
        if anchor not in anchors:
            anchors.append(anchor)

    @property
    def text(self) -> str:
        return blocks_to_text(self.blocks)

    @property
    def title(self) -> str:
        heading = next(
            (
                str(block.get("text") or "")
                for block in self.blocks
                if block.get("type") == "heading" and block.get("text")
            ),
            "",
        )
        return " ".join((heading or "".join(self.title_parts)).split()).strip()


def blocks_to_text(blocks: list[dict]) -> str:
    return "\n\n".join(
        str(block["text"]).strip()
        for block in blocks
        if block.get("type") not in {"divider", "pagebreak", "figure"}
        and str(block.get("text", "")).strip()
    )


def blocks_to_analysis_text(blocks: list[dict]) -> str:
    return blocks_to_text(
        [
            block
            for block in blocks
            if not NOTE_SEMANTICS.intersection(
                str(block.get("semantic_type") or "").casefold().split()
            )
        ]
    )


def looks_chinese(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    return len(CHINESE_CHARACTER_PATTERN.findall(compact)) / len(compact) >= 0.12


def _line_block(line: str) -> dict[str, str]:
    value = line.strip()
    if DIVIDER_PATTERN.fullmatch(value):
        return {"type": "divider", "text": ""}
    if value.startswith(">"):
        return {"type": "quote", "text": value.lstrip(">").strip()}
    return {"type": "paragraph", "text": value}


def text_to_blocks(text: str, *, source_format: str = "text") -> list[dict[str, str]]:
    """Build safe reader blocks without carrying source CSS or arbitrary HTML."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    if source_format == "txt":
        groups = [
            group
            for group in re.split(r"\n\s*\n+", normalized)
            if group.strip()
        ]
        blocks: list[dict[str, str]] = []
        for group in groups:
            lines = [line for line in group.splitlines() if line.strip()]
            if looks_chinese(group):
                blocks.extend(_line_block(line) for line in lines)
            else:
                blocks.append(
                    {
                        "type": "paragraph",
                        "text": " ".join(line.strip() for line in lines),
                    }
                )
        return blocks

    groups = [
        group
        for group in re.split(r"\n\s*\n+", normalized)
        if group.strip()
    ]
    blocks: list[dict[str, str]] = []
    for group in groups:
        lines = [line.strip() for line in group.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            blocks.append(_line_block(lines[0]))
            continue
        if source_format == "pdf":
            blocks.append({"type": "paragraph", "text": " ".join(lines)})
        else:
            blocks.extend(_line_block(line) for line in lines)
    return blocks


def ensure_chapter_blocks(chapter: dict, *, source_format: str) -> dict:
    enriched = dict(chapter)
    existing = enriched.get("blocks")
    if not isinstance(existing, list) or not existing:
        enriched["blocks"] = text_to_blocks(
            str(enriched.get("text") or ""),
            source_format=source_format,
        )
    enriched.setdefault("structural_path", [])
    enriched.setdefault("content_type", "chapter")
    enriched.setdefault("source_locator", {})
    enriched.setdefault("structure_version", "")
    enriched.setdefault("structure_confidence", "")
    enriched.setdefault("structure_warnings", [])
    return enriched


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def normalize_preview(text: str, limit: int = 600) -> str:
    return " ".join(text.split())[:limit]


def normalize_section_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title, flags=re.UNICODE).casefold()


def is_numbered_chapter_title(title: str) -> bool:
    return bool(title.strip() and CHAPTER_PATTERN.fullmatch(title.strip()))


def is_non_mainline_title(title: str) -> bool:
    normalized = normalize_section_title(title)
    return bool(
        not normalized
        or ZERO_CHAPTER_PATTERN.match(title.strip())
        or normalized in NON_MAINLINE_EXACT_TITLES
        or normalized.startswith(("abouttheauthor", "copyright"))
        or any(fragment in normalized for fragment in NON_MAINLINE_TITLE_FRAGMENTS)
        or re.fullmatch(r"致.+读者", normalized)
    )


def select_mainline_chapters(sections: list[dict]) -> list[dict]:
    candidates = [
        section
        for section in sections
        if not is_non_mainline_title(str(section.get("title") or ""))
    ]
    numbered = [
        section
        for section in candidates
        if is_numbered_chapter_title(str(section.get("title") or ""))
    ]
    selected = numbered or candidates
    chapters: list[dict] = []
    for number, section in enumerate(selected, start=1):
        chapter = dict(section)
        chapter["number"] = number
        chapters.append(chapter)
    return chapters


def normalize_epub_subjects(values: list[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        for candidate in re.split(r"[,，、;；|/]+", value):
            tag = " ".join(candidate.split())
            if tag and len(tag) <= 40 and tag not in tags:
                tags.append(tag)
    return tags[:8]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def first_element_text(root: ElementTree.Element, name: str) -> str | None:
    return next(
        (
            " ".join("".join(item.itertext()).split())
            for item in root.iter()
            if local_name(item.tag) == name and "".join(item.itertext()).strip()
        ),
        None,
    )


def epub_translator(root: ElementTree.Element) -> str | None:
    contributors: dict[str, str] = {}
    translator_ids: set[str] = set()
    for item in root.iter():
        if local_name(item.tag) != "contributor":
            continue
        value = " ".join("".join(item.itertext()).split())
        item_id = next(
            (
                attribute_value
                for attribute_name, attribute_value in item.attrib.items()
                if local_name(attribute_name) == "id"
            ),
            "",
        )
        if item_id and value:
            contributors[item_id] = value
        roles = {
            role.lower()
            for attribute_name, attribute_value in item.attrib.items()
            if local_name(attribute_name) == "role"
            for role in re.split(r"[\s,;]+", attribute_value)
            if role
        }
        if value and roles.intersection({"trl", "translator", "译者"}):
            return value

    for item in root.iter():
        if local_name(item.tag) != "meta" or item.attrib.get("property") != "role":
            continue
        role = " ".join("".join(item.itertext()).split()).lower()
        refines = item.attrib.get("refines", "").lstrip("#")
        if role in {"trl", "translator", "译者"} and refines:
            translator_ids.add(refines)
    return next(
        (value for item_id, value in contributors.items() if item_id in translator_ids),
        None,
    )


def extract_isbn(text: str) -> str | None:
    match = re.search(
        r"(?i)\bISBN(?:-1[03])?\s*[:：]?\s*((?:97[89][\s-]?)?[0-9][0-9Xx\s-]{8,20})",
        text,
    )
    return " ".join(match.group(1).split()) if match else None


def extract_labeled_value(text: str, labels: tuple[str, ...], limit: int) -> str | None:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?im)^\s*(?:{joined})\s*[:：]\s*(.+?)\s*$", text[:12000])
    if not match:
        return None
    value = " ".join(match.group(1).split())
    return value[:limit] or None


def front_matter_metadata(text: str) -> dict[str, str | list[str] | None]:
    tags_value = extract_labeled_value(text, ("标签", "主题", "分类"), 320)
    return {
        "title": extract_labeled_value(text, ("书名", "作品名"), 300),
        "author": extract_labeled_value(text, ("作者", "著者"), 200),
        "publisher": extract_labeled_value(text, ("出版社", "出版者"), 200),
        "translator": extract_labeled_value(text, ("译者", "翻译"), 200),
        "isbn": extract_isbn(text[:12000]),
        "tags": normalize_epub_subjects([tags_value] if tags_value else []),
    }


def build_metadata_context(chapters: list[dict], raw_text: str = "", limit: int = 8000) -> str:
    headings = "\n".join(
        str(item.get("title") or "") for item in chapters[:30] if item.get("title")
    )
    opening_sections = "\n\n".join(
        f"{item.get('title') or ''}\n{item.get('text') or ''}" for item in chapters[:5]
    )
    return f"章节或目录标题：\n{headings}\n\n开篇、序章或目录内容：\n{raw_text or opening_sections}"[
        :limit
    ]


def epub_cover_data_url(
    archive: zipfile.ZipFile,
    *,
    base: PurePosixPath,
    manifest_items: dict[str, dict[str, str]],
    opf: ElementTree.Element,
) -> str | None:
    cover_id = next(
        (
            item.attrib.get("content")
            for item in opf.iter()
            if local_name(item.tag) == "meta"
            and item.attrib.get("name", "").lower() == "cover"
            and item.attrib.get("content")
        ),
        None,
    )
    cover_item = next(
        (
            item
            for item_id, item in manifest_items.items()
            if "cover-image" in item.get("properties", "").split() or item_id == cover_id
        ),
        None,
    )
    if not cover_item:
        return None
    media_type = cover_item.get("media-type", "").lower()
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        return None
    resource = safe_epub_path(base, cover_item.get("href", "").split("#", 1)[0])
    if resource not in archive.namelist():
        return None
    content = archive.read(resource)
    if not content or len(content) > 4 * 1024 * 1024:
        return None
    return f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"


def split_text_chapters(
    text: str,
    *,
    source_format: str = "text",
) -> list[dict]:
    matches = list(CHAPTER_PATTERN.finditer(text))
    if not matches:
        start = len(text) - len(text.lstrip())
        clean = text.strip()
        return [
            {
                "number": 1,
                "title": "",
                "characters": len(clean),
                "text": clean,
                "blocks": text_to_blocks(clean, source_format=source_format),
                "source_locator": {
                    "format": source_format,
                    "start_char": start,
                    "end_char": start + len(clean),
                },
            }
        ]

    chapters: list[dict] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw_body = text[start:end]
        leading = len(raw_body) - len(raw_body.lstrip())
        body = raw_body.strip()
        body_start = start + leading
        title = " ".join(match.group(1).split())[:160]
        if is_non_mainline_title(title):
            continue
        chapters.append(
            {
                "number": len(chapters) + 1,
                "title": title,
                "characters": len(body),
                "text": body,
                "blocks": text_to_blocks(body, source_format=source_format),
                "source_locator": {
                    "format": source_format,
                    "start_char": body_start,
                    "end_char": body_start + len(body),
                },
            }
        )
    return chapters


def add_pdf_page_locators(
    chapters: list[dict],
    page_breaks: list[dict[str, int]],
) -> list[dict]:
    for chapter in chapters:
        locator = dict(chapter.get("source_locator") or {})
        start = int(locator.get("start_char", 0))
        end = int(locator.get("end_char", start + len(str(chapter.get("text") or ""))))
        containing = [item for item in page_breaks if item["offset"] <= start]
        first = containing[-1] if containing else page_breaks[0]
        relevant = [first, *[item for item in page_breaks if start < item["offset"] < end]]
        relative_breaks: list[dict[str, int]] = []
        seen_pages: set[int] = set()
        for item in relevant:
            if item["page"] in seen_pages:
                continue
            seen_pages.add(item["page"])
            relative_breaks.append(
                {
                    "page": item["page"],
                    "offset": max(0, item["offset"] - start),
                }
            )
        locator.update(
            {
                "format": "pdf",
                "page_start": relative_breaks[0]["page"],
                "page_end": relative_breaks[-1]["page"],
                "page_breaks": relative_breaks,
            }
        )
        chapter["source_locator"] = locator
    return chapters


def source_title(path: Path, original_name: str | None) -> str:
    return Path(original_name).stem if original_name else path.stem


def parse_txt(path: Path, original_name: str | None = None) -> ParsedBook:
    text = decode_text(path.read_bytes())
    fallback = source_title(path, original_name)
    metadata = front_matter_metadata(text)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    inferred_title = (
        first_line
        if first_line
        and len(first_line) <= 160
        and CHAPTER_PATTERN.fullmatch(first_line) is None
        and not re.match(r"^\s*(?:作者|出版社|出版者|译者|翻译|ISBN|标签|主题|分类)\s*[:：]", first_line)
        else fallback
    )
    chapters = split_text_chapters(text, source_format="txt")
    return ParsedBook(
        title=str(metadata["title"] or inferred_title),
        chapters=chapters,
        preview=normalize_preview(text),
        tags=list(metadata["tags"] or []),
        author=metadata["author"] if isinstance(metadata["author"], str) else None,
        publisher=metadata["publisher"] if isinstance(metadata["publisher"], str) else None,
        translator=metadata["translator"] if isinstance(metadata["translator"], str) else None,
        isbn=metadata["isbn"] if isinstance(metadata["isbn"], str) else None,
        metadata_context=build_metadata_context(chapters, text[:6000]),
    )


def safe_epub_path(base: PurePosixPath, relative: str) -> str:
    normalized = posixpath.normpath(base.joinpath(unquote(relative)).as_posix())
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ValueError("EPUB 包含不安全的资源路径")
    return normalized


def attribute_value(element: ElementTree.Element, name: str) -> str:
    return next(
        (
            value
            for attribute_name, value in element.attrib.items()
            if local_name(attribute_name) == name
        ),
        "",
    )


def direct_children(
    element: ElementTree.Element,
    name: str,
) -> list[ElementTree.Element]:
    return [item for item in list(element) if local_name(item.tag) == name]


def resolve_epub_href(document_resource: str, href: str) -> tuple[str, str]:
    decoded = unquote(href).strip()
    if not decoded or decoded.startswith(("http:", "https:", "mailto:", "data:")):
        return "", ""
    resource_href, separator, fragment = decoded.partition("#")
    resource = (
        safe_epub_path(PurePosixPath(document_resource).parent, resource_href)
        if resource_href
        else document_resource
    )
    return resource, fragment if separator else ""


def ncx_navigation(
    archive: zipfile.ZipFile,
    *,
    opf: ElementTree.Element,
    base: PurePosixPath,
    manifest_items: dict[str, dict[str, str]],
) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    spine_element = next(
        (item for item in opf.iter() if local_name(item.tag) == "spine"),
        None,
    )
    toc_id = spine_element.attrib.get("toc", "") if spine_element is not None else ""
    ncx_item = manifest_items.get(toc_id)
    if not ncx_item:
        ncx_item = next(
            (
                item
                for item in manifest_items.values()
                if item.get("media-type") == "application/x-dtbncx+xml"
            ),
            None,
        )
    if not ncx_item or not ncx_item.get("href"):
        return [], warnings
    ncx_resource = safe_epub_path(base, ncx_item["href"].split("#", 1)[0])
    if ncx_resource not in archive.namelist():
        return [], [f"EPUB 2 目录文件不存在：{ncx_resource}"]
    try:
        root = ElementTree.fromstring(archive.read(ncx_resource))
    except ElementTree.ParseError:
        return [], ["EPUB 2 NCX 目录无法解析"]

    nav_map = next(
        (item for item in root.iter() if local_name(item.tag) == "navMap"),
        None,
    )
    if nav_map is None:
        return [], ["EPUB 2 NCX 缺少 navMap"]

    def convert(point: ElementTree.Element, parents: list[str]) -> dict:
        label_element = next(
            (
                item
                for item in point.iter()
                if local_name(item.tag) == "navLabel"
            ),
            None,
        )
        title = (
            " ".join("".join(label_element.itertext()).split())
            if label_element is not None
            else ""
        )
        content = next(
            (
                item
                for item in direct_children(point, "content")
                if item.attrib.get("src")
            ),
            None,
        )
        raw_href = content.attrib.get("src", "") if content is not None else ""
        resource, fragment = (
            resolve_epub_href(ncx_resource, raw_href)
            if raw_href
            else ("", "")
        )
        path = [*parents, title] if title else list(parents)
        return {
            "title": title,
            "resource": resource,
            "fragment": fragment,
            "href": raw_href,
            "semantic_type": point.attrib.get("class", ""),
            "path": path,
            "children": [
                convert(child, path)
                for child in direct_children(point, "navPoint")
            ],
        }

    return [
        convert(point, [])
        for point in direct_children(nav_map, "navPoint")
    ], warnings


def epub3_navigation(
    archive: zipfile.ZipFile,
    *,
    base: PurePosixPath,
    manifest_items: dict[str, dict[str, str]],
) -> tuple[list[dict], list[str]]:
    nav_item = next(
        (
            item
            for item in manifest_items.values()
            if "nav" in item.get("properties", "").split()
        ),
        None,
    )
    if not nav_item or not nav_item.get("href"):
        return [], []
    nav_resource = safe_epub_path(base, nav_item["href"].split("#", 1)[0])
    if nav_resource not in archive.namelist():
        return [], [f"EPUB 3 导航文件不存在：{nav_resource}"]
    try:
        root = ElementTree.fromstring(archive.read(nav_resource))
    except ElementTree.ParseError:
        return [], ["EPUB 3 Nav 目录无法解析"]
    nav_elements = [
        item for item in root.iter() if local_name(item.tag) == "nav"
    ]
    toc_nav = next(
        (
            item
            for item in nav_elements
            if "toc" in attribute_value(item, "type").casefold().split()
        ),
        nav_elements[0] if nav_elements else None,
    )
    if toc_nav is None:
        return [], ["EPUB 3 导航文件缺少 nav 元素"]
    root_list = next(iter(direct_children(toc_nav, "ol")), None)
    if root_list is None:
        return [], ["EPUB 3 目录缺少有序列表"]

    def convert(item: ElementTree.Element, parents: list[str]) -> dict:
        label_element = next(
            (
                child
                for child in list(item)
                if local_name(child.tag) in {"a", "span"}
            ),
            None,
        )
        title = (
            " ".join("".join(label_element.itertext()).split())
            if label_element is not None
            else ""
        )
        raw_href = (
            label_element.attrib.get("href", "")
            if label_element is not None and local_name(label_element.tag) == "a"
            else ""
        )
        resource, fragment = (
            resolve_epub_href(nav_resource, raw_href)
            if raw_href
            else ("", "")
        )
        path = [*parents, title] if title else list(parents)
        nested = next(iter(direct_children(item, "ol")), None)
        return {
            "title": title,
            "resource": resource,
            "fragment": fragment,
            "href": raw_href,
            "semantic_type": (
                attribute_value(label_element, "type")
                if label_element is not None
                else ""
            ),
            "path": path,
            "children": (
                [
                    convert(child, path)
                    for child in direct_children(nested, "li")
                ]
                if nested is not None
                else []
            ),
        }

    return [
        convert(item, [])
        for item in direct_children(root_list, "li")
    ], []


def flatten_structure(nodes: list[dict]) -> list[dict]:
    flattened: list[dict] = []
    for node in nodes:
        flattened.append(node)
        flattened.extend(flatten_structure(list(node.get("children") or [])))
    return flattened


def structure_for_storage(nodes: list[dict]) -> list[dict]:
    return [
        {
            "title": str(node.get("title") or ""),
            "href": str(node.get("href") or ""),
            "resource": str(node.get("resource") or ""),
            "fragment": str(node.get("fragment") or ""),
            "semantic_type": str(node.get("semantic_type") or ""),
            "children": structure_for_storage(list(node.get("children") or [])),
        }
        for node in nodes
    ]


def is_non_mainline_navigation_node(node: dict) -> bool:
    semantics = set(
        str(node.get("semantic_type") or "").casefold().split()
    )
    return bool(
        semantics.intersection(NON_MAINLINE_SEMANTICS)
        or is_non_mainline_title(str(node.get("title") or ""))
    )


def valid_navigation_target(node: dict, documents: dict[str, dict]) -> bool:
    resource = str(node.get("resource") or "")
    if resource not in documents:
        return False
    fragment = str(node.get("fragment") or "")
    return not fragment or fragment in documents[resource]["anchors"]


def navigation_leaf_nodes(
    nodes: list[dict],
    documents: dict[str, dict],
) -> list[dict]:
    def collect(node: dict) -> list[dict]:
        descendants = [
            leaf
            for child in list(node.get("children") or [])
            for leaf in collect(child)
        ]
        if descendants:
            return descendants
        if (
            valid_navigation_target(node, documents)
            and not is_non_mainline_navigation_node(node)
        ):
            return [node]
        return []

    return [leaf for node in nodes for leaf in collect(node)]


def strip_matching_heading(blocks: list[dict], title: str) -> list[dict]:
    if (
        blocks
        and blocks[0].get("type") == "heading"
        and normalize_section_title(str(blocks[0].get("text") or ""))
        == normalize_section_title(title)
    ):
        return blocks[1:]
    return blocks


def chapters_from_navigation(
    nodes: list[dict],
    documents: dict[str, dict],
    *,
    source: str,
) -> tuple[list[dict], str, list[str]]:
    all_nodes = [node for node in flatten_structure(nodes) if node.get("href")]
    valid_nodes = [
        node for node in all_nodes if valid_navigation_target(node, documents)
    ]
    leaves = navigation_leaf_nodes(nodes, documents)
    if not leaves:
        return [], "low", ["目录没有产生可定位的正文章节"]

    starts: dict[int, int] = {}
    for index, leaf in enumerate(leaves):
        document = documents[str(leaf["resource"])]
        fragment = str(leaf.get("fragment") or "")
        starts[index] = (
            int(document["anchors"][fragment])
            if fragment
            else 0
        )

    chapters: list[dict] = []
    heading_matches = 0
    for index, leaf in enumerate(leaves):
        resource = str(leaf["resource"])
        document = documents[resource]
        start = starts[index]
        later_starts = [
            starts[other_index]
            for other_index in range(index + 1, len(leaves))
            if str(leaves[other_index]["resource"]) == resource
            and starts[other_index] > start
        ]
        end = min(later_starts) if later_starts else len(document["blocks"])
        raw_blocks = list(document["blocks"][start:end])
        title = str(leaf.get("title") or "")
        if (
            raw_blocks
            and raw_blocks[0].get("type") == "heading"
            and normalize_section_title(str(raw_blocks[0].get("text") or ""))
            == normalize_section_title(title)
        ):
            heading_matches += 1
        blocks = strip_matching_heading(raw_blocks, title)
        text = blocks_to_analysis_text(blocks).strip()
        if not text:
            continue
        chapters.append(
            {
                "number": len(chapters) + 1,
                "title": title,
                "characters": len(text),
                "text": text,
                "blocks": blocks,
                "structural_path": list(leaf.get("path") or [title]),
                "structure_source": source,
                "content_type": "chapter",
                "source_locator": {
                    "format": "epub",
                    "resource": resource,
                    "fragment": str(leaf.get("fragment") or ""),
                    "spine_index": document["spine_index"],
                },
            }
        )

    target_ratio = len(valid_nodes) / len(all_nodes) if all_nodes else 0
    heading_ratio = heading_matches / len(leaves) if leaves else 0
    confidence = (
        "high"
        if target_ratio >= 0.9 and heading_ratio >= 0.7
        else "medium"
        if target_ratio >= 0.7
        else "low"
    )
    warnings: list[str] = []
    unresolved = len(all_nodes) - len(valid_nodes)
    if unresolved:
        warnings.append(f"目录中有 {unresolved} 个目标无法定位")
    if heading_ratio < 0.7:
        warnings.append("部分目录标题与正文锚点标题不一致")
    return chapters, confidence, warnings


def chapters_from_headings(documents: dict[str, dict]) -> list[dict]:
    chapters: list[dict] = []
    for resource, document in sorted(
        documents.items(),
        key=lambda item: int(item[1]["spine_index"]),
    ):
        headings = [
            {
                "index": index,
                "level": int(block.get("level") or 6),
                "title": str(block.get("text") or ""),
                "fragment": next(iter(block.get("anchors") or []), ""),
            }
            for index, block in enumerate(document["blocks"])
            if block.get("type") == "heading" and block.get("text")
        ]
        if not headings:
            continue
        stack: list[dict] = []
        for heading in headings:
            while stack and int(stack[-1]["level"]) >= int(heading["level"]):
                stack.pop()
            heading["path"] = [
                *[str(parent["title"]) for parent in stack],
                str(heading["title"]),
            ]
            heading["parent"] = stack[-1] if stack else None
            heading["has_children"] = False
            if stack:
                stack[-1]["has_children"] = True
            stack.append(heading)

        for heading_index, heading in enumerate(headings):
            title = str(heading["title"])
            if heading["has_children"] or is_non_mainline_title(title):
                continue
            start = int(heading["index"])
            end = next(
                (
                    int(candidate["index"])
                    for candidate in headings[heading_index + 1 :]
                    if int(candidate["level"]) <= int(heading["level"])
                ),
                len(document["blocks"]),
            )
            blocks = strip_matching_heading(
                list(document["blocks"][start:end]),
                title,
            )
            text = blocks_to_analysis_text(blocks).strip()
            if not text:
                continue
            chapters.append(
                {
                    "number": len(chapters) + 1,
                    "title": title,
                    "characters": len(text),
                    "text": text,
                    "blocks": blocks,
                    "structural_path": list(heading["path"]),
                    "structure_source": "content_headings",
                    "content_type": "chapter",
                    "source_locator": {
                        "format": "epub",
                        "resource": resource,
                        "fragment": str(heading["fragment"]),
                        "spine_index": document["spine_index"],
                    },
                }
            )
    return chapters


def structure_version_for(source: str, chapters: list[dict]) -> str:
    payload = [
        {
            "title": chapter.get("title"),
            "path": chapter.get("structural_path"),
            "locator": chapter.get("source_locator"),
        }
        for chapter in chapters
    ]
    digest = hashlib.sha256(
        json.dumps(
            {"source": source, "chapters": payload},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"{EPUB_PARSER_VERSION}-{digest[:16]}"


def split_creator_metadata(
    creator: str | None,
    translator: str | None,
) -> tuple[str | None, str | None]:
    value = " ".join((creator or "").split()).strip()
    if not value:
        return None, translator
    if translator:
        return re.sub(r"\s*(?:著|编著)\s*$", "", value).strip(), translator
    match = re.match(
        r"^(?P<author>.+?)\s*(?:著|编著)\s*[;；]\s*(?P<translator>.+?)\s*译\s*$",
        value,
    )
    if not match:
        return value, None
    return match.group("author").strip(), match.group("translator").strip()


def parse_epub(path: Path, original_name: str | None = None) -> ParsedBook:
    with zipfile.ZipFile(path) as archive:
        expanded_size = sum(item.file_size for item in archive.infolist())
        if expanded_size > 200 * 1024 * 1024:
            raise ValueError("EPUB 解压后体积超过 200 MB")

        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(
            (
                item.attrib.get("full-path")
                for item in container.iter()
                if item.tag.endswith("rootfile")
            ),
            None,
        )
        if not rootfile:
            raise ValueError("EPUB 缺少 OPF 根文件")

        opf = ElementTree.fromstring(archive.read(rootfile))
        book_title = first_element_text(opf, "title") or source_title(path, original_name)
        raw_creator = first_element_text(opf, "creator")
        publisher = first_element_text(opf, "publisher")
        translator = epub_translator(opf)
        author, translator = split_creator_metadata(raw_creator, translator)
        language = first_element_text(opf, "language")
        identifiers = [
            " ".join("".join(item.itertext()).split())
            for item in opf.iter()
            if local_name(item.tag) == "identifier"
        ]
        isbn_candidates = [extract_isbn(f"ISBN: {value}") for value in identifiers if value]
        isbn = next((value for value in isbn_candidates if value), None)
        subjects = normalize_epub_subjects(
            [
                "".join(item.itertext()).strip()
                for item in opf.iter()
                if local_name(item.tag) == "subject"
            ]
        )
        manifest_items = {
            item.attrib["id"]: {
                "href": item.attrib.get("href", ""),
                "media-type": item.attrib.get("media-type", ""),
                "properties": item.attrib.get("properties", ""),
                "fallback": item.attrib.get("fallback", ""),
            }
            for item in opf.iter()
            if local_name(item.tag) == "item" and "id" in item.attrib
        }
        spine = [
            {
                "idref": item.attrib.get("idref", ""),
                "linear": item.attrib.get("linear", "yes").casefold() != "no",
            }
            for item in opf.iter()
            if local_name(item.tag) == "itemref"
        ]
        base = PurePosixPath(rootfile).parent
        names = set(archive.namelist())
        cover_data_url = epub_cover_data_url(
            archive,
            base=base,
            manifest_items=manifest_items,
            opf=opf,
        )
        documents: dict[str, dict] = {}
        sections: list[dict] = []

        for spine_index, spine_item in enumerate(spine):
            item_id = str(spine_item["idref"])
            manifest_item = manifest_items.get(item_id, {})
            href = manifest_item.get("href")
            if not href:
                continue
            properties = manifest_item.get("properties", "").split()
            if "nav" in properties or "cover-image" in properties:
                continue
            resource = safe_epub_path(base, href.split("#", 1)[0])
            if resource not in names:
                continue
            collector = HtmlTextCollector()
            collector.feed(decode_text(archive.read(resource)))
            collector.close()
            blocks = list(collector.blocks)
            for block in blocks:
                if block.get("type") != "figure" or not block.get("src"):
                    continue
                try:
                    image_resource, image_fragment = resolve_epub_href(
                        resource,
                        str(block["src"]),
                    )
                except ValueError:
                    block["resource"] = ""
                    block["unsafe"] = True
                else:
                    block["resource"] = image_resource
                    if image_fragment:
                        block["fragment"] = image_fragment
                    if image_resource not in names:
                        block["missing"] = True
            documents[resource] = {
                "title": collector.title,
                "blocks": blocks,
                "anchors": dict(collector.anchors),
                "spine_index": spine_index,
                "linear": bool(spine_item["linear"]),
            }
            title = collector.title
            section_blocks = strip_matching_heading(list(blocks), title)
            text = blocks_to_analysis_text(section_blocks).strip()
            if not text:
                continue
            sections.append(
                {
                    "number": len(sections) + 1,
                    "title": title,
                    "characters": len(text),
                    "text": text,
                    "blocks": section_blocks,
                    "structural_path": [title] if title else [],
                    "structure_source": "spine",
                    "content_type": "chapter",
                    "source_locator": {
                        "format": "epub",
                        "resource": resource,
                        "fragment": "",
                        "spine_index": spine_index,
                    },
                }
            )

        nav_nodes, structure_warnings = epub3_navigation(
            archive,
            base=base,
            manifest_items=manifest_items,
        )
        structure_source = "epub_nav"
        if not nav_nodes:
            ncx_nodes, ncx_warnings = ncx_navigation(
                archive,
                opf=opf,
                base=base,
                manifest_items=manifest_items,
            )
            nav_nodes = ncx_nodes
            structure_warnings.extend(ncx_warnings)
            structure_source = "epub_ncx" if nav_nodes else ""

        chapters: list[dict] = []
        structure_confidence = "low"
        if nav_nodes:
            chapters, structure_confidence, navigation_warnings = (
                chapters_from_navigation(
                    nav_nodes,
                    documents,
                    source=structure_source,
                )
            )
            structure_warnings.extend(navigation_warnings)

        heading_chapters = chapters_from_headings(documents)
        if not chapters or (
            structure_confidence == "low"
            and len(heading_chapters) > len(chapters)
        ):
            if chapters:
                structure_warnings.append(
                    "目录定位置信度较低，已改用正文标题层级"
                )
            chapters = heading_chapters
            if chapters:
                structure_source = "content_headings"
                structure_confidence = "medium"
        if not chapters:
            chapters = select_mainline_chapters(
                [
                    section
                    for section in sections
                    if documents[
                        str(section["source_locator"]["resource"])
                    ]["linear"]
                ]
            )
            structure_source = "spine"
            structure_confidence = "low"
            structure_warnings.append(
                "EPUB 没有可用目录或标题层级，已按线性阅读文件边界切分"
            )
        if not chapters:
            raise ValueError("EPUB 中没有识别到正式主线正文章节")

        total_characters = sum(int(chapter["characters"]) for chapter in chapters)
        oversized = [
            chapter
            for chapter in chapters
            if int(chapter["characters"]) > 50_000
            or (
                total_characters > 0
                and int(chapter["characters"]) / total_characters > 0.8
                and int(chapter["characters"]) > 20_000
            )
        ]
        structure_requires_review = bool(oversized)
        if oversized:
            structure_confidence = "low"
            structure_warnings.append(
                f"检测到 {len(oversized)} 个异常偏长章节，需要检查章节结构"
            )

        structure_version = structure_version_for(structure_source, chapters)
        for chapter in chapters:
            chapter["structure_version"] = structure_version
            chapter["structure_confidence"] = structure_confidence
            chapter["structure_warnings"] = list(dict.fromkeys(structure_warnings))

        preview_source = str(chapters[0].get("text") or "")
        return ParsedBook(
            title=book_title or source_title(path, original_name),
            chapters=chapters,
            preview=normalize_preview(preview_source),
            tags=subjects,
            author=author,
            publisher=publisher,
            translator=translator,
            isbn=isbn,
            language=language,
            metadata_context=build_metadata_context(chapters),
            cover_data_url=cover_data_url,
            structure_version=structure_version,
            structure_source=structure_source,
            structure_confidence=structure_confidence,
            structure_warnings=list(dict.fromkeys(structure_warnings)),
            structure=structure_for_storage(nav_nodes),
            structure_requires_review=structure_requires_review,
            parser_version=EPUB_PARSER_VERSION,
            metadata={
                "language": language,
                "creator": author,
                "translator": translator,
                "package_version": opf.attrib.get("version", ""),
                "unique_identifier": opf.attrib.get("unique-identifier", ""),
            },
        )


def parse_pdf(path: Path, original_name: str | None = None) -> ParsedBook:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("PDF 已加密，无法解析") from exc

    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text_parts: list[str] = []
    page_breaks: list[dict[str, int]] = []
    offset = 0
    for page_number, page_text in enumerate(pages, start=1):
        if not page_text:
            continue
        page_breaks.append({"page": page_number, "offset": offset})
        text_parts.append(page_text)
        offset += len(page_text) + 1
    text = "\n".join(text_parts)
    if not text:
        raise ValueError("PDF 没有可提取文字，扫描版需要 OCR")
    metadata_title = (
        str(reader.metadata.title)
        if reader.metadata and reader.metadata.title
        else source_title(path, original_name)
    )
    metadata_author = (
        str(reader.metadata.author) if reader.metadata and reader.metadata.author else None
    )
    front_metadata = front_matter_metadata(text)
    chapters = add_pdf_page_locators(
        split_text_chapters(text, source_format="pdf"),
        page_breaks,
    )
    return ParsedBook(
        title=str(front_metadata["title"] or metadata_title),
        chapters=chapters,
        preview=normalize_preview(text),
        tags=list(front_metadata["tags"] or []),
        author=(
            front_metadata["author"]
            if isinstance(front_metadata["author"], str)
            else metadata_author
        ),
        publisher=(
            front_metadata["publisher"]
            if isinstance(front_metadata["publisher"], str)
            else None
        ),
        translator=(
            front_metadata["translator"]
            if isinstance(front_metadata["translator"], str)
            else None
        ),
        isbn=front_metadata["isbn"] if isinstance(front_metadata["isbn"], str) else None,
        metadata_context=build_metadata_context(chapters, "\n\n".join(pages[:5])),
    )


def parse_book(path: Path, source_format: str, original_name: str | None = None) -> ParsedBook:
    if source_format == "txt":
        return parse_txt(path, original_name)
    if source_format == "epub":
        return parse_epub(path, original_name)
    if source_format == "pdf":
        return parse_pdf(path, original_name)
    raise ValueError(f"不支持的文件格式：{source_format}")
