import base64
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
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
    metadata_context: str = ""
    cover_data_url: str | None = None


class HtmlTextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[dict[str, str]] = []
        self.block_parts: list[str] = []
        self.block_type = "paragraph"
        self.title_parts: list[str] = []
        self.open_tags: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        current_tag = tag.lower()
        self.open_tags.append(current_tag)
        if current_tag in {"script", "style", "nav"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if current_tag in BLOCK_TAG_TYPES:
            self.flush_block()
            self.block_type = BLOCK_TAG_TYPES[current_tag]
        elif current_tag == "br":
            self.block_parts.append("\n")
        elif current_tag == "hr":
            self.flush_block()
            self.blocks.append({"type": "divider", "text": ""})

    def handle_endtag(self, tag: str) -> None:
        current_tag = tag.lower()
        if current_tag in {"script", "style", "nav"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and current_tag in BLOCK_TAG_TYPES:
            self.flush_block()
        for index in range(len(self.open_tags) - 1, -1, -1):
            if self.open_tags[index] == current_tag:
                del self.open_tags[index]
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
            self.blocks.append({"type": self.block_type, "text": value})
        self.block_type = "paragraph"

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


def blocks_to_text(blocks: list[dict[str, str]]) -> str:
    return "\n\n".join(
        block["text"].strip()
        for block in blocks
        if block.get("type") != "divider" and block.get("text", "").strip()
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
    normalized = base.joinpath(relative).as_posix()
    if normalized.startswith("../") or "/../" in normalized:
        raise ValueError("EPUB 包含不安全的资源路径")
    return normalized


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
        author = first_element_text(opf, "creator")
        publisher = first_element_text(opf, "publisher")
        translator = epub_translator(opf)
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
            }
            for item in opf.iter()
            if item.tag.endswith("item") and "id" in item.attrib
        }
        spine = [
            item.attrib.get("idref", "")
            for item in opf.iter()
            if item.tag.endswith("itemref")
        ]
        base = PurePosixPath(rootfile).parent
        names = set(archive.namelist())
        cover_data_url = epub_cover_data_url(
            archive,
            base=base,
            manifest_items=manifest_items,
            opf=opf,
        )
        sections: list[dict] = []

        for spine_index, item_id in enumerate(spine):
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
            title = collector.title
            blocks = list(collector.blocks)
            if (
                blocks
                and blocks[0].get("type") == "heading"
                and normalize_section_title(str(blocks[0].get("text") or ""))
                == normalize_section_title(title)
            ):
                blocks = blocks[1:]
            text = blocks_to_text(blocks).strip()
            if not text:
                continue
            sections.append(
                {
                    "number": len(sections) + 1,
                    "title": title,
                    "characters": len(text),
                    "text": text,
                    "blocks": blocks,
                    "source_locator": {
                        "format": "epub",
                        "resource": resource,
                        "spine_index": spine_index,
                    },
                }
            )

        chapters = select_mainline_chapters(sections)
        if not chapters:
            raise ValueError("EPUB 中没有识别到正式主线正文章节")
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
            metadata_context=build_metadata_context(chapters),
            cover_data_url=cover_data_url,
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
