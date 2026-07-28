from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BookImport, Chapter, Edition
from .parsers import EPUB_PARSER_VERSION, ParsedBook, blocks_to_analysis_text, parse_book


def apply_parsed_book(book_import: BookImport, parsed: ParsedBook) -> None:
    book_import.chapters = parsed.chapters
    book_import.chapter_count = len(parsed.chapters)
    book_import.preview = parsed.preview
    book_import.language = parsed.language
    book_import.parser_version = parsed.parser_version or None
    book_import.structure_version = parsed.structure_version or None
    book_import.structure_source = parsed.structure_source or None
    book_import.structure_confidence = parsed.structure_confidence
    book_import.structure_warnings = list(parsed.structure_warnings or [])
    book_import.structure_tree = list(parsed.structure or [])
    book_import.structure_requires_review = parsed.structure_requires_review
    if parsed.title:
        book_import.detected_title = parsed.title
    if parsed.author:
        book_import.detected_author = parsed.author
    if parsed.publisher:
        book_import.publisher = parsed.publisher
    if parsed.translator:
        book_import.translator = parsed.translator
    if parsed.isbn:
        book_import.isbn = parsed.isbn


def sync_edition_chapters(
    session: Session,
    *,
    book_import: BookImport,
    edition: Edition,
) -> None:
    existing = {
        chapter.number: chapter
        for chapter in session.scalars(
            select(Chapter)
            .where(Chapter.edition_id == edition.id)
            .order_by(Chapter.number)
        )
    }
    retained_numbers: set[int] = set()
    for index, item in enumerate(book_import.chapters):
        number = int(item.get("number", index + 1))
        retained_numbers.add(number)
        locator = dict(item.get("source_locator") or {})
        locator.update(
            {
                "import_id": book_import.id,
                "index": index,
                "structure_version": book_import.structure_version,
                "structural_path": list(item.get("structural_path") or []),
            }
        )
        text_fingerprint = hashlib.sha256(
            str(item.get("text") or "").encode("utf-8")
        ).hexdigest()
        chapter = existing.get(number)
        if chapter is None:
            session.add(
                Chapter(
                    edition_id=edition.id,
                    number=number,
                    title=str(item.get("title") or "")[:300],
                    source_locator=locator,
                    text_fingerprint=text_fingerprint,
                )
            )
            continue
        chapter.title = str(item.get("title") or "")[:300]
        chapter.source_locator = locator
        chapter.text_fingerprint = text_fingerprint

    for number, chapter in existing.items():
        if number not in retained_numbers:
            session.delete(chapter)


def _reviewed_structure_tree(chapters: list[dict]) -> list[dict]:
    root: list[dict] = []
    for chapter in chapters:
        children = root
        path = list(chapter.get("structural_path") or [chapter["title"]])
        for depth, title in enumerate(path):
            node = next(
                (item for item in children if item.get("title") == title),
                None,
            )
            if node is None:
                node = {"title": title, "children": []}
                children.append(node)
            if depth == len(path) - 1:
                node["chapter_number"] = chapter["number"]
                node["href"] = ""
            children = node["children"]
    return root


def apply_reviewed_structure(
    book_import: BookImport,
    chapter_drafts: list[dict],
) -> None:
    """Apply a lossless, user-reviewed chapter structure.

    Draft segments may split and merge existing chapters, but they must cover
    every source block exactly once and in the original reading order.
    """
    source_chapters = {
        int(chapter.get("number", index + 1)): chapter
        for index, chapter in enumerate(book_import.chapters)
    }
    expected = [
        (source_number, block_index)
        for source_number, chapter in source_chapters.items()
        for block_index in range(len(chapter.get("blocks") or []))
    ]
    consumed: list[tuple[int, int]] = []
    reviewed: list[dict] = []
    version_payload: list[dict] = []

    if not chapter_drafts:
        raise ValueError("reviewed structure must contain at least one chapter")

    for number, draft in enumerate(chapter_drafts, start=1):
        title = " ".join(str(draft.get("title") or "").split()).strip()
        if not title:
            raise ValueError("every reviewed chapter must have a title")
        parent_path = [
            " ".join(str(item).split()).strip()
            for item in draft.get("parent_path") or []
            if " ".join(str(item).split()).strip()
        ]
        blocks: list[dict] = []
        normalized_segments: list[dict[str, int]] = []
        for segment in draft.get("segments") or []:
            source_number = int(segment.get("source_number", 0))
            start_block = int(segment.get("start_block", -1))
            end_block = int(segment.get("end_block", -1))
            source = source_chapters.get(source_number)
            source_blocks = list(source.get("blocks") or []) if source else []
            if (
                source is None
                or start_block < 0
                or end_block <= start_block
                or end_block > len(source_blocks)
            ):
                raise ValueError("reviewed structure contains an invalid source segment")
            blocks.extend(copy.deepcopy(source_blocks[start_block:end_block]))
            consumed.extend(
                (source_number, block_index)
                for block_index in range(start_block, end_block)
            )
            normalized_segments.append(
                {
                    "source_number": source_number,
                    "start_block": start_block,
                    "end_block": end_block,
                }
            )

        text = blocks_to_analysis_text(blocks).strip()
        if not text:
            raise ValueError("every reviewed chapter must contain narrative text")
        structural_path = [*parent_path, title]
        reviewed.append(
            {
                "number": number,
                "title": title,
                "characters": len(text),
                "text": text,
                "blocks": blocks,
                "structural_path": structural_path,
                "structure_source": "manual_review",
                "content_type": "chapter",
                "source_locator": {
                    "format": book_import.source_format,
                    "segments": normalized_segments,
                },
            }
        )
        version_payload.append(
            {
                "title": title,
                "parent_path": parent_path,
                "segments": normalized_segments,
            }
        )

    if consumed != expected:
        raise ValueError("reviewed structure must cover every source block exactly once")

    digest = hashlib.sha256(
        json.dumps(
            {
                "previous": book_import.structure_version,
                "chapters": version_payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    structure_version = f"{EPUB_PARSER_VERSION}-manual-{digest[:16]}"
    review_warning = "章节结构已由上传者人工确认"
    for chapter in reviewed:
        chapter["structure_version"] = structure_version
        chapter["structure_confidence"] = "high"
        chapter["structure_warnings"] = [review_warning]

    book_import.chapters = reviewed
    book_import.chapter_count = len(reviewed)
    book_import.preview = str(reviewed[0]["text"])[:800]
    book_import.structure_version = structure_version
    book_import.structure_source = "manual_review"
    book_import.structure_confidence = "high"
    book_import.structure_warnings = [review_warning]
    book_import.structure_tree = _reviewed_structure_tree(reviewed)
    book_import.structure_requires_review = False


def reparse_import_structure(
    session: Session,
    *,
    book_import: BookImport,
    edition: Edition,
) -> bool:
    parsed = parse_book(
        Path(book_import.stored_path),
        book_import.source_format,
        book_import.original_name,
    )
    previous_version = book_import.structure_version
    apply_parsed_book(book_import, parsed)
    changed = previous_version != book_import.structure_version
    if parsed.language:
        edition.language = parsed.language
    edition.structure_version = book_import.structure_version
    if changed:
        edition.revision += 1
    sync_edition_chapters(
        session,
        book_import=book_import,
        edition=edition,
    )
    return changed
