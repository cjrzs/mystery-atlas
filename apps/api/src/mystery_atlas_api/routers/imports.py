import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal, get_session
from ..models import BookImport, User
from ..parsers import parse_book
from ..schemas import BookImportResponse
from ..security import get_current_user

router = APIRouter(prefix="/imports", tags=["private book imports"])
ALLOWED_FORMATS = {".epub": "epub", ".txt": "txt", ".pdf": "pdf"}


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
            book_import.stage = "ready_for_analysis"
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
    maximum = settings.max_upload_mb * 1024 * 1024
    size = 0
    digest = hashlib.sha256()

    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.max_upload_mb} MB")
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
