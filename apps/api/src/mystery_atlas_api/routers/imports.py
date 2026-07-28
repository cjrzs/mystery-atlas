import hashlib
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..analysis_dispatch import schedule_analysis
from ..book_metadata import suggest_book_metadata
from ..book_structure import (
    apply_parsed_book,
    apply_reviewed_structure,
    sync_edition_chapters,
)
from ..config import get_settings
from ..database import SessionLocal, get_session
from ..models import (
    AnalysisJob,
    BookImport,
    Edition,
    PrivateLibraryBook,
    User,
    Work,
    utcnow,
)
from ..parsers import parse_book
from ..schemas import (
    AnalysisJobDetailResponse,
    BookImportResponse,
    FinalizeImportRequest,
    ReviewBookStructureRequest,
)
from ..security import get_current_user
from ..tagging import normalize_book_tags

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
            book_import.stage = "detecting_metadata"
            book_import.progress = 80
            apply_parsed_book(book_import, parsed)
            session.commit()

            metadata = suggest_book_metadata(parsed)
            book_import.detected_title = metadata.title
            book_import.detected_author = metadata.author
            book_import.publisher = metadata.publisher
            book_import.translator = metadata.translator
            book_import.isbn = normalize_isbn(metadata.isbn)
            book_import.detected_tags = metadata.tags

            book_import.status = "completed"
            book_import.stage = (
                "structure_review_required"
                if book_import.structure_requires_review
                else "awaiting_confirmation"
            )
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
    background_tasks: BackgroundTasks,
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
    if book_import.structure_requires_review:
        raise HTTPException(status_code=409, detail="请先复核并保存章节结构")
    if request.visibility == "public":
        if not user.email_verified or not user.can_publish:
            raise HTTPException(status_code=403, detail="当前账户不能公开上传")
        if not request.rights_confirmed:
            raise HTTPException(status_code=422, detail="公开上传必须确认传播授权")

    title = (book_import.detected_title or Path(book_import.original_name).stem).strip()
    author = (book_import.detected_author or "作者待识别").strip()
    isbn = normalize_isbn(book_import.isbn)
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
        .where(func.lower(Work.title) == title.lower())
        .where(func.lower(Work.author) == author.lower())
    )
    if work is None and request.visibility == "private":
        work = session.scalar(
            select(Work)
            .where(Work.visibility == "private")
            .where(Work.owner_id == user.id)
            .where(func.lower(Work.title) == title.lower())
            .where(func.lower(Work.author) == author.lower())
        )

    if work is None:
        work = Work(
            slug=make_slug(title, session),
            title=title,
            author=author,
            tags=normalize_book_tags(book_import.detected_tags),
            status="analyzing",
            visibility=request.visibility,
            owner_id=user.id,
            maintainer_id=user.id,
            analysis_progress=15,
        )
        session.add(work)
        session.flush()
    elif book_import.detected_tags and (
        work.visibility == "private" or work.maintainer_id == user.id
    ):
        work.tags = normalize_book_tags(book_import.detected_tags)

    edition = Edition(
        work_id=work.id,
        title=title,
        publisher=book_import.publisher.strip() if book_import.publisher else None,
        translator=book_import.translator.strip() if book_import.translator else None,
        isbn=isbn,
        language=book_import.language or "zh-CN",
        source_format=book_import.source_format,
        content_fingerprint=book_import.content_hash,
        is_public_reference=request.visibility == "public",
        visibility=request.visibility,
        maintainer_id=user.id,
        rights_confirmed=request.rights_confirmed,
        structure_version=book_import.structure_version,
    )
    session.add(edition)
    session.flush()

    sync_edition_chapters(
        session,
        book_import=book_import,
        edition=edition,
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
    analysis_job = AnalysisJob(
        work_id=work.id,
        edition_id=edition.id,
        track="full",
        stage=(
            "structure_review"
            if book_import.structure_requires_review
            else "source_validation"
        ),
        status=(
            "waiting_structure_review"
            if book_import.structure_requires_review
            else "queued"
        ),
        progress=0,
        structure_version=book_import.structure_version,
    )
    session.add(analysis_job)
    session.flush()
    if not book_import.structure_requires_review:
        schedule_analysis(analysis_job, background_tasks, get_settings())

    book_import.detected_title = title
    book_import.detected_author = author
    book_import.publisher = book_import.publisher.strip() if book_import.publisher else None
    book_import.translator = book_import.translator.strip() if book_import.translator else None
    book_import.isbn = isbn
    book_import.visibility = request.visibility
    book_import.rights_confirmed = request.rights_confirmed
    book_import.work_id = work.id
    book_import.edition_id = edition.id
    book_import.finalized_at = utcnow()
    book_import.stage = (
        "structure_review_required"
        if book_import.structure_requires_review
        else "ready_for_analysis"
    )
    session.commit()
    session.refresh(book_import)
    return book_import


@router.put("/{import_id}/structure", response_model=BookImportResponse)
def review_import_structure(
    import_id: str,
    request: ReviewBookStructureRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookImport:
    book_import = session.get(BookImport, import_id)
    if book_import is None or book_import.user_id != user.id:
        raise HTTPException(status_code=404, detail="导入记录不存在")
    if book_import.status != "completed":
        raise HTTPException(status_code=409, detail="文件尚未完成基础解析")
    if not book_import.structure_requires_review:
        raise HTTPException(status_code=409, detail="当前章节结构不在待复核状态")

    try:
        apply_reviewed_structure(
            book_import,
            [chapter.model_dump() for chapter in request.chapters],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    book_import.stage = (
        "ready_for_analysis"
        if book_import.finalized_at is not None
        else "awaiting_confirmation"
    )
    if book_import.edition_id is not None:
        edition = session.get(Edition, book_import.edition_id)
        if edition is None:
            raise HTTPException(status_code=404, detail="书籍版本不存在")
        edition.structure_version = book_import.structure_version
        edition.revision += 1
        sync_edition_chapters(
            session,
            book_import=book_import,
            edition=edition,
        )
        job = session.scalar(
            select(AnalysisJob)
            .where(AnalysisJob.edition_id == edition.id)
            .order_by(AnalysisJob.created_at.desc())
        )
        if job is not None:
            job.structure_version = book_import.structure_version
            job.result_summary = {}
            schedule_analysis(job, background_tasks, get_settings())
        work = session.get(Work, edition.work_id)
        if work is not None:
            work.status = "analyzing"
            work.analysis_progress = 0

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


@router.get(
    "/{import_id}/analysis",
    response_model=AnalysisJobDetailResponse,
)
def get_import_analysis(
    import_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AnalysisJob:
    book_import = session.get(BookImport, import_id)
    if book_import is None or book_import.user_id != user.id:
        raise HTTPException(status_code=404, detail="导入记录不存在")
    if book_import.edition_id is None:
        raise HTTPException(status_code=409, detail="书籍尚未确认入库")
    job = session.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.edition_id == book_import.edition_id)
        .order_by(AnalysisJob.created_at.desc())
    )
    if job is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return job
