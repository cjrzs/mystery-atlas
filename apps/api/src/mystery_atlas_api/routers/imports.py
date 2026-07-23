import hashlib
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal, get_session
from ..models import (
    AnalysisJob,
    BookImport,
    Chapter,
    Edition,
    PrivateLibraryBook,
    User,
    Work,
    utcnow,
)
from ..parsers import parse_book
from ..schemas import BookImportResponse, FinalizeImportRequest
from ..security import get_current_user

router = APIRouter(prefix="/imports", tags=["book imports"])
ALLOWED_FORMATS = {".epub": "epub", ".txt": "txt", ".pdf": "pdf"}


def normalize_isbn(value: str | None) -> str | None:
    normalized = re.sub(r"[^0-9Xx]", "", value or "").upper()
    return normalized or None


def normalized(value: str) -> str:
    return "".join(value.lower().split())


def make_slug(title: str, session: Session) -> str:
    stem = "-".join(re.findall(r"[a-z0-9]+", title.lower()))[:80] or "work"
    candidate = f"{stem}-{uuid4().hex[:8]}"
    while session.scalar(select(Work.id).where(Work.slug == candidate)) is not None:
        candidate = f"{stem}-{uuid4().hex[:8]}"
    return candidate


def parse_import_job(import_id: str) -> None:
    with SessionLocal() as session:
        book_import = session.get(BookImport, import_id)
        if book_import is None:
            return
        try:
            book_import.status = "parsing"
            book_import.stage = "extracting_text"
            book_import.progress = 35
            session.commit()

            parsed = parse_book(
                Path(book_import.stored_path),
                book_import.source_format,
                book_import.original_name,
            )
            book_import.stage = "detecting_chapters"
            book_import.progress = 80
            book_import.detected_title = parsed.title
            book_import.chapters = parsed.chapters
            book_import.chapter_count = len(parsed.chapters)
            book_import.preview = parsed.preview
            session.commit()

            book_import.status = "completed"
            book_import.stage = "awaiting_confirmation"
            book_import.progress = 100
            session.commit()
        except Exception as exc:
            book_import.status = "failed"
            book_import.stage = "failed"
            book_import.error = str(exc)[:1000]
            session.commit()


@router.post("", response_model=BookImportResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_import(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookImport:
    filename = Path(file.filename or "book").name
    suffix = Path(filename).suffix.lower()
    source_format = ALLOWED_FORMATS.get(suffix)
    if source_format is None:
        raise HTTPException(status_code=415, detail="仅支持 EPUB、TXT 和 PDF")

    settings = get_settings()
    target_dir = Path(settings.upload_dir) / user.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid4()}{suffix}"
    maximum = min(settings.max_upload_mb, user.upload_quota_mb) * 1024 * 1024
    used = session.scalar(
        select(func.coalesce(func.sum(BookImport.size_bytes), 0)).where(BookImport.user_id == user.id)
    ) or 0
    size = 0
    digest = hashlib.sha256()

    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件不能超过 {settings.max_upload_mb} MB",
                    )
                if used + size > maximum:
                    raise HTTPException(status_code=413, detail="个人存储额度不足")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    book_import = BookImport(
        user_id=user.id,
        original_name=filename,
        stored_path=str(target.resolve()),
        source_format=source_format,
        size_bytes=size,
        content_hash=digest.hexdigest(),
        status="queued",
        stage="waiting",
        progress=5,
    )
    session.add(book_import)
    session.commit()
    session.refresh(book_import)
    background_tasks.add_task(parse_import_job, book_import.id)
    return book_import


@router.post("/{import_id}/finalize", response_model=BookImportResponse)
def finalize_import(
    import_id: str,
    request: FinalizeImportRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookImport:
    book_import = session.get(BookImport, import_id)
    if book_import is None or book_import.user_id != user.id:
        raise HTTPException(status_code=404, detail="导入记录不存在")
    if book_import.status != "completed":
        raise HTTPException(status_code=409, detail="文件尚未完成基础解析")
    if book_import.finalized_at is not None:
        return book_import
    if request.visibility == "public":
        if not user.email_verified or not user.can_publish:
            raise HTTPException(status_code=403, detail="当前账户不能公开上传")
        if not request.rights_confirmed:
            raise HTTPException(status_code=422, detail="公开上传必须确认传播授权")

    isbn = normalize_isbn(request.isbn)
    duplicate_conditions = [Edition.content_fingerprint == book_import.content_hash]
    if isbn:
        duplicate_conditions.append(Edition.isbn == isbn)
    public_duplicate = session.scalar(
        select(Edition)
        .where(Edition.visibility == "public")
        .where(or_(*duplicate_conditions))
    )
    if public_duplicate is not None:
        duplicate_work = session.get(Work, public_duplicate.work_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "公共档案中已经存在相同版本",
                "work_slug": duplicate_work.slug if duplicate_work else None,
            },
        )

    own_duplicate = session.scalar(
        select(BookImport)
        .where(BookImport.user_id == user.id)
        .where(BookImport.id != book_import.id)
        .where(BookImport.content_hash == book_import.content_hash)
        .where(BookImport.finalized_at.is_not(None))
    )
    if own_duplicate is not None:
        raise HTTPException(status_code=409, detail="你的档案中已经存在相同文件")

    work = session.scalar(
        select(Work)
        .where(Work.visibility == "public")
        .where(func.lower(Work.title) == request.title.strip().lower())
        .where(func.lower(Work.author) == request.author.strip().lower())
    )
    if work is None and request.visibility == "private":
        work = session.scalar(
            select(Work)
            .where(Work.visibility == "private")
            .where(Work.owner_id == user.id)
            .where(func.lower(Work.title) == request.title.strip().lower())
            .where(func.lower(Work.author) == request.author.strip().lower())
        )

    if work is None:
        work = Work(
            slug=make_slug(request.title, session),
            title=request.title.strip(),
            author=request.author.strip(),
            status="analyzing",
            visibility=request.visibility,
            owner_id=user.id,
            maintainer_id=user.id,
            analysis_progress=15,
        )
        session.add(work)
        session.flush()

    edition = Edition(
        work_id=work.id,
        title=request.title.strip(),
        publisher=request.publisher.strip() if request.publisher else None,
        translator=request.translator.strip() if request.translator else None,
        isbn=isbn,
        source_format=book_import.source_format,
        content_fingerprint=book_import.content_hash,
        is_public_reference=request.visibility == "public",
        visibility=request.visibility,
        maintainer_id=user.id,
        rights_confirmed=request.rights_confirmed,
    )
    session.add(edition)
    session.flush()

    for index, item in enumerate(book_import.chapters):
        session.add(
            Chapter(
                edition_id=edition.id,
                number=int(item.get("number", index + 1)),
                title=str(item.get("title") or f"章节 {index + 1}")[:300],
                source_locator={"import_id": book_import.id, "index": index},
            )
        )

    library_item = PrivateLibraryBook(
        user_id=user.id,
        work_id=work.id,
        edition_id=edition.id,
        import_id=book_import.id,
        object_key=f"{user.id}:{edition.id}",
        kind="public_owner" if request.visibility == "public" else "private_upload",
    )
    session.add(library_item)
    session.add(
        AnalysisJob(
            work_id=work.id,
            edition_id=edition.id,
            track="reading",
            stage="chapter_segmentation",
            status="queued",
            progress=10,
        )
    )

    book_import.detected_title = request.title.strip()
    book_import.detected_author = request.author.strip()
    book_import.publisher = request.publisher.strip() if request.publisher else None
    book_import.translator = request.translator.strip() if request.translator else None
    book_import.isbn = isbn
    book_import.visibility = request.visibility
    book_import.rights_confirmed = request.rights_confirmed
    book_import.work_id = work.id
    book_import.edition_id = edition.id
    book_import.finalized_at = utcnow()
    book_import.stage = "ready_for_analysis"
    session.commit()
    session.refresh(book_import)
    return book_import


@router.get("", response_model=list[BookImportResponse])
def list_imports(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[BookImport]:
    return list(
        session.scalars(
            select(BookImport)
            .where(BookImport.user_id == user.id)
            .order_by(BookImport.created_at.desc())
        )
    )


@router.get("/{import_id}", response_model=BookImportResponse)
def get_import(
    import_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookImport:
    book_import = session.get(BookImport, import_id)
    if book_import is None or book_import.user_id != user.id:
        raise HTTPException(status_code=404, detail="导入记录不存在")
    return book_import
