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


@dataclass
class ParsedBook:
    title: str
    chapters: list[dict]
    preview: str


class HtmlTextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.heading_parts: list[str] = []
        self.title_parts: list[str] = []
        self.current_tag = ""
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.current_tag = tag.lower()
        if self.current_tag in {"script", "style", "nav"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "nav"} and self.ignored_depth:
            self.ignored_depth -= 1
        self.current_tag = ""

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.parts.append(value)
        if self.current_tag in {"h1", "h2", "h3"} and len("".join(self.heading_parts)) < 160:
            self.heading_parts.append(value)
        if self.current_tag == "title" and len("".join(self.title_parts)) < 160:
            self.title_parts.append(value)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)

    @property
    def title(self) -> str:
        return " ".join(self.heading_parts or self.title_parts).strip()


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def normalize_preview(text: str, limit: int = 600) -> str:
    return " ".join(text.split())[:limit]


def split_text_chapters(text: str) -> list[dict]:
    matches = list(CHAPTER_PATTERN.finditer(text))
    if not matches:
        clean = text.strip()
        return [{"number": 1, "title": "正文", "characters": len(clean), "text": clean}]

    chapters: list[dict] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        chapters.append(
            {
                "number": index + 1,
                "title": " ".join(match.group(1).split())[:160],
                "characters": len(body),
                "text": body,
            }
        )
    return chapters


def source_title(path: Path, original_name: str | None) -> str:
    return Path(original_name).stem if original_name else path.stem


def parse_txt(path: Path, original_name: str | None = None) -> ParsedBook:
    text = decode_text(path.read_bytes())
    fallback = source_title(path, original_name)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    title = (
        first_line
        if first_line and len(first_line) <= 160 and CHAPTER_PATTERN.fullmatch(first_line) is None
        else fallback
    )
    return ParsedBook(
        title=title,
        chapters=split_text_chapters(text),
        preview=normalize_preview(text),
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
        book_title = next(
            ("".join(item.itertext()).strip() for item in opf.iter() if item.tag.endswith("title")),
            source_title(path, original_name),
        )
        manifest = {
            item.attrib["id"]: item.attrib.get("href", "")
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
        chapters: list[dict] = []
        preview_source = ""

        for item_id in spine:
            href = manifest.get(item_id)
            if not href:
                continue
            resource = safe_epub_path(base, href.split("#", 1)[0])
            if resource not in names:
                continue
            collector = HtmlTextCollector()
            collector.feed(decode_text(archive.read(resource)))
            text = collector.text.strip()
            if not text:
                continue
            if not preview_source:
                preview_source = text
            chapters.append(
                {
                    "number": len(chapters) + 1,
                    "title": collector.title or f"章节 {len(chapters) + 1}",
                    "characters": len(text),
                    "text": text,
                }
            )

        if not chapters:
            raise ValueError("EPUB 目录中没有可读取的正文")
        return ParsedBook(
            title=book_title or source_title(path, original_name),
            chapters=chapters,
            preview=normalize_preview(preview_source),
        )


def parse_pdf(path: Path, original_name: str | None = None) -> ParsedBook:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("PDF 已加密，无法解析") from exc

    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n".join(page for page in pages if page)
    if not text:
        raise ValueError("PDF 没有可提取文字，扫描版需要 OCR")
    metadata_title = (
        str(reader.metadata.title)
        if reader.metadata and reader.metadata.title
        else source_title(path, original_name)
    )
    return ParsedBook(
        title=metadata_title,
        chapters=split_text_chapters(text),
        preview=normalize_preview(text),
    )


def parse_book(path: Path, source_format: str, original_name: str | None = None) -> ParsedBook:
    if source_format == "txt":
        return parse_txt(path, original_name)
    if source_format == "epub":
        return parse_epub(path, original_name)
    if source_format == "pdf":
        return parse_pdf(path, original_name)
    raise ValueError(f"不支持的文件格式：{source_format}")
