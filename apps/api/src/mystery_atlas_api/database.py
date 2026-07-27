from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def ensure_development_columns() -> None:
    """Keep create_all-based SQLite databases usable while migrations remain authoritative."""
    if not settings.database_url.startswith("sqlite"):
        return
    additions = {
        "users": {
            "email_verified": "BOOLEAN NOT NULL DEFAULT 1",
            "can_publish": "BOOLEAN NOT NULL DEFAULT 1",
            "upload_quota_mb": "INTEGER NOT NULL DEFAULT 500",
            "reader_preferences": "JSON NOT NULL DEFAULT '{}'",
        },
        "works": {
            "visibility": "VARCHAR(20) NOT NULL DEFAULT 'public'",
            "owner_id": "VARCHAR(36)",
            "maintainer_id": "VARCHAR(36)",
            "analysis_progress": "INTEGER NOT NULL DEFAULT 0",
            "unresolved_feedback_count": "INTEGER NOT NULL DEFAULT 0",
            "tags": "JSON NOT NULL DEFAULT '[]'",
        },
        "editions": {
            "translator": "VARCHAR(200)",
            "visibility": "VARCHAR(20) NOT NULL DEFAULT 'private'",
            "maintainer_id": "VARCHAR(36)",
            "is_available": "BOOLEAN NOT NULL DEFAULT 1",
            "rights_confirmed": "BOOLEAN NOT NULL DEFAULT 0",
            "revision": "INTEGER NOT NULL DEFAULT 1",
        },
        "book_imports": {
            "visibility": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "detected_author": "VARCHAR(300)",
            "detected_tags": "JSON NOT NULL DEFAULT '[]'",
            "publisher": "VARCHAR(200)",
            "translator": "VARCHAR(200)",
            "isbn": "VARCHAR(32)",
            "rights_confirmed": "BOOLEAN NOT NULL DEFAULT 0",
            "work_id": "VARCHAR(36)",
            "edition_id": "VARCHAR(36)",
            "finalized_at": "DATETIME",
        },
        "private_library_books": {
            "import_id": "VARCHAR(36)",
            "kind": "VARCHAR(32) NOT NULL DEFAULT 'private_upload'",
        },
        "analysis_jobs": {
            "heartbeat_at": "DATETIME",
            "current_call_id": "VARCHAR(36)",
            "stage_detail": "VARCHAR(300)",
            "response_chars": "INTEGER NOT NULL DEFAULT 0",
            "content_idle_seconds": "INTEGER NOT NULL DEFAULT 0",
        },
    }
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table_name, columns in additions.items():
            if table_name not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, declaration in columns.items():
                if column_name not in existing:
                    connection.execute(
                        text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {declaration}')
                    )
