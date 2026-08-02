from .models import BookImport, Edition, Work
from .parsers import ensure_chapter_blocks
from .schemas import ReaderChapter, ReaderChapterSummary, ReaderResponse


def chapter_summary(chapter: dict) -> ReaderChapterSummary:
    text = str(chapter.get("text") or "")
    return ReaderChapterSummary(
        number=int(chapter.get("number") or 0),
        title=str(chapter.get("title") or ""),
        characters=int(chapter.get("characters") or len(text)),
        structural_path=list(chapter.get("structural_path") or []),
        content_type=str(chapter.get("content_type") or "chapter"),
    )


def reader_response(
    work: Work,
    edition: Edition,
    book_import: BookImport,
) -> ReaderResponse:
    return ReaderResponse(
        work_id=work.id,
        work_slug=work.slug,
        work_title=work.title,
        author=work.author,
        edition_id=edition.id,
        edition_title=edition.title,
        language=edition.language,
        visibility=edition.visibility,
        chapters=[chapter_summary(chapter) for chapter in book_import.chapters],
        structure_version=book_import.structure_version or "",
        structure_source=book_import.structure_source or "",
        structure_confidence=book_import.structure_confidence,
        structure_warnings=list(book_import.structure_warnings or []),
        structure_requires_review=book_import.structure_requires_review,
    )


def reader_chapter(
    book_import: BookImport,
    chapter_number: int,
) -> ReaderChapter | None:
    chapter = next(
        (
            candidate
            for candidate in book_import.chapters
            if int(candidate.get("number") or 0) == chapter_number
        ),
        None,
    )
    if chapter is None:
        return None

    normalized = ensure_chapter_blocks(
        chapter,
        source_format=book_import.source_format,
    )
    text = str(normalized.get("text") or "")
    normalized.update(
        number=chapter_number,
        title=str(normalized.get("title") or ""),
        text=text,
        characters=int(normalized.get("characters") or len(text)),
    )
    return ReaderChapter.model_validate(normalized)
