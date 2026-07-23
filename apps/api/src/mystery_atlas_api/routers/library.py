from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import BookImport, Edition, PrivateLibraryBook, User, Work
from ..schemas import LibraryItemResponse, ProgressUpdate, ReaderResponse
from ..security import get_current_user

router = APIRouter(prefix="/library", tags=["private archive"])


def serialize_item(item: PrivateLibraryBook, user: User, session: Session) -> LibraryItemResponse:
    work = session.get(Work, item.work_id) if item.work_id else None
    edition = session.get(Edition, item.edition_id) if item.edition_id else None
    return LibraryItemResponse(
        id=item.id,
        kind=item.kind,
        work_id=work.id if work else None,
        work_slug=work.slug if work else None,
        edition_id=edition.id if edition else None,
        title=work.title if work else "已删除的作品",
        author=work.author if work else "",
        visibility=edition.visibility if edition else "unavailable",
        current_chapter=item.current_chapter,
        progress=item.progress,
        analysis_progress=work.analysis_progress if work else 0,
        is_maintainer=bool(
            (work and work.maintainer_id == user.id)
            or (edition and edition.maintainer_id == user.id)
        ),
        updated_at=item.updated_at,
    )


@router.get("", response_model=list[LibraryItemResponse])
def list_library(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[LibraryItemResponse]:
    items = list(
        session.scalars(
            select(PrivateLibraryBook)
            .where(PrivateLibraryBook.user_id == user.id)
            .order_by(PrivateLibraryBook.updated_at.desc())
        )
    )
    return [serialize_item(item, user, session) for item in items]


@router.post(
    "/public/{edition_id}",
    response_model=LibraryItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_public_reading_record(
    edition_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> LibraryItemResponse:
    edition = session.get(Edition, edition_id)
    if edition is None or edition.visibility != "public" or not edition.is_available:
        raise HTTPException(status_code=404, detail="公共版本不存在")
    work = session.get(Work, edition.work_id)
    if work is None or work.visibility != "public":
        raise HTTPException(status_code=404, detail="公共作品不存在")
    item = session.scalar(
        select(PrivateLibraryBook).where(
            PrivateLibraryBook.user_id == user.id,
            PrivateLibraryBook.edition_id == edition.id,
        )
    )
    if item is None:
        item = PrivateLibraryBook(
            user_id=user.id,
            work_id=work.id,
            edition_id=edition.id,
            object_key=f"{user.id}:{edition.id}",
            kind="public_reading",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
    return serialize_item(item, user, session)


@router.get("/{item_id}/reader", response_model=ReaderResponse)
def get_private_reader(
    item_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ReaderResponse:
    item = session.get(PrivateLibraryBook, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="私人档案不存在")
    work = session.get(Work, item.work_id) if item.work_id else None
    edition = session.get(Edition, item.edition_id) if item.edition_id else None
    if work is None or edition is None:
        raise HTTPException(status_code=404, detail="书籍版本不可用")
    book_import = session.scalar(
        select(BookImport)
        .where(BookImport.edition_id == edition.id)
        .where(BookImport.finalized_at.is_not(None))
    )
    if book_import is None:
        raise HTTPException(status_code=404, detail="版本正文不可用")
    return ReaderResponse(
        work_id=work.id,
        work_slug=work.slug,
        work_title=work.title,
        author=work.author,
        edition_id=edition.id,
        edition_title=edition.title,
        visibility=edition.visibility,
        chapters=book_import.chapters,
    )


@router.patch("/{item_id}/progress", response_model=LibraryItemResponse)
def update_progress(
    item_id: str,
    request: ProgressUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> LibraryItemResponse:
    item = session.get(PrivateLibraryBook, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="私人档案不存在")
    item.current_chapter = request.current_chapter
    item.progress = request.progress
    session.commit()
    session.refresh(item)
    return serialize_item(item, user, session)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_library_record(
    item_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    item = session.get(PrivateLibraryBook, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="私人档案不存在")
    session.delete(item)
    session.commit()
