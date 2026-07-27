from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import BookImport
from .parsers import parse_book, text_to_blocks


def resolve_source_path(book_import: BookImport, upload_root: Path | None = None) -> Path:
    stored = Path(book_import.stored_path)
    if stored.is_file():
        return stored
    if upload_root is not None:
        parts = [part for part in re.split(r"[\\/]+", book_import.stored_path) if part]
        lowered = [part.casefold() for part in parts]
        if "uploads" in lowered:
            relative = parts[lowered.index("uploads") + 1 :]
            candidate = upload_root.joinpath(*relative)
            if candidate.is_file():
                return candidate
        candidate = upload_root / book_import.user_id / stored.name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"source file is missing for import {book_import.id}")


def _locator_key(chapter: dict) -> tuple[str, str] | None:
    locator = dict(chapter.get("source_locator") or {})
    for name in ("resource", "start_char", "page_start", "index"):
        value = locator.get(name)
        if value is not None:
            return name, str(value)
    return None


def has_reader_blocks(chapters: list[dict]) -> bool:
    return bool(chapters) and all(
        isinstance(chapter.get("blocks"), list) for chapter in chapters
    )


def merge_reader_blocks(
    existing: list[dict],
    parsed: list[dict],
    *,
    source_format: str = "text",
) -> list[dict]:
    by_locator = {
        key: chapter
        for chapter in parsed
        if (key := _locator_key(chapter)) is not None
    }
    by_number = {
        int(chapter.get("number") or index): chapter
        for index, chapter in enumerate(parsed, start=1)
    }
    merged: list[dict] = []
    for index, chapter in enumerate(existing, start=1):
        source = by_locator.get(_locator_key(chapter) or ("", ""))
        if source is None:
            source = by_number.get(int(chapter.get("number") or index))
        blocks = source.get("blocks") if source else None
        if not isinstance(blocks, list) or not blocks:
            blocks = text_to_blocks(
                str(chapter.get("text") or ""),
                source_format=source_format,
            )
        if not blocks and chapter.get("text"):
            raise ValueError(
                f"could not rebuild formatted content for chapter {chapter.get('number') or index}"
            )
        enriched = dict(chapter)
        enriched["blocks"] = blocks
        merged.append(enriched)
    if len(merged) != len(existing):
        raise ValueError("chapter count changed while rebuilding reader content")
    return merged


def backfill_reader_content(
    session: Session,
    *,
    upload_root: Path | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }
    imports = list(session.scalars(select(BookImport).order_by(BookImport.created_at.asc())))
    for book_import in imports:
        report["processed"] = int(report["processed"]) + 1
        chapters = list(book_import.chapters or [])
        if book_import.status != "completed" or not chapters:
            report["skipped"] = int(report["skipped"]) + 1
            continue
        if has_reader_blocks(chapters):
            report["skipped"] = int(report["skipped"]) + 1
            continue
        try:
            source_path = resolve_source_path(book_import, upload_root)
            parsed = parse_book(
                source_path,
                book_import.source_format,
                book_import.original_name,
            )
            book_import.chapters = merge_reader_blocks(
                chapters,
                parsed.chapters,
                source_format=book_import.source_format,
            )
            session.commit()
            report["updated"] = int(report["updated"]) + 1
        except Exception as exc:
            session.rollback()
            report["failed"] = int(report["failed"]) + 1
            errors = report["errors"]
            assert isinstance(errors, list)
            errors.append(
                {
                    "import_id": book_import.id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild semantic reader blocks from retained source files."
    )
    parser.add_argument(
        "--upload-root",
        type=Path,
        default=Path(get_settings().upload_dir),
    )
    arguments = parser.parse_args()
    with SessionLocal() as session:
        report = backfill_reader_content(
            session,
            upload_root=arguments.upload_root,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
