from pathlib import Path

import sqlalchemy as sa

from mystery_atlas_api.database import Base
from mystery_atlas_api.deployment import migrate_legacy_data
from mystery_atlas_api.reader_backfill import has_reader_blocks, merge_reader_blocks


def test_reader_backfill_treats_an_empty_chapter_as_already_formatted() -> None:
    assert has_reader_blocks(
        [
            {"number": 1, "blocks": [{"type": "paragraph", "text": "正文"}]},
            {"number": 2, "blocks": []},
        ]
    )


def test_reader_backfill_adds_blocks_without_changing_stored_text() -> None:
    existing = [
        {
            "number": 1,
            "title": "第一章",
            "text": "原有正文，不应改写。",
            "source_locator": {"resource": "chapter-1.xhtml"},
        }
    ]
    parsed = [
        {
            "number": 1,
            "title": "第一章",
            "text": "重新解析的正文。",
            "blocks": [{"type": "paragraph", "text": "重新解析的正文。"}],
            "source_locator": {"resource": "chapter-1.xhtml"},
        }
    ]

    merged = merge_reader_blocks(existing, parsed)

    assert merged[0]["text"] == "原有正文，不应改写。"
    assert merged[0]["blocks"] == parsed[0]["blocks"]


def test_reader_backfill_preserves_unmatched_historical_chapters() -> None:
    existing = [
        {
            "number": 4,
            "title": "历史附章",
            "text": "第一段。\n第二段。",
            "source_locator": {"resource": "legacy-appendix.xhtml"},
        }
    ]

    merged = merge_reader_blocks(existing, [], source_format="epub")

    assert merged[0]["title"] == "历史附章"
    assert merged[0]["blocks"] == [
        {"type": "paragraph", "text": "第一段。"},
        {"type": "paragraph", "text": "第二段。"},
    ]


def test_legacy_sqlite_migration_copies_rows_missing_new_columns(
    tmp_path: Path,
) -> None:
    legacy_database = tmp_path / "legacy.db"
    target_database = tmp_path / "target.db"
    legacy_uploads = tmp_path / "legacy-uploads"
    target_uploads = tmp_path / "target-uploads"
    legacy_uploads.mkdir()

    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(500), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("can_publish", sa.Boolean(), nullable=False),
        sa.Column("upload_quota_mb", sa.Integer(), nullable=False),
    )
    legacy_engine = sa.create_engine(f"sqlite:///{legacy_database.as_posix()}")
    metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            users.insert(),
            {
                "id": "legacy-user",
                "email": "legacy@example.com",
                "password_hash": "hash",
                "display_name": "Legacy Reader",
                "role": "admin",
                "is_active": True,
                "email_verified": True,
                "can_publish": True,
                "upload_quota_mb": 500,
            },
        )

    target_url = f"sqlite:///{target_database.as_posix()}"
    target_engine = sa.create_engine(target_url)
    Base.metadata.create_all(target_engine)

    report = migrate_legacy_data(
        legacy_database=legacy_database,
        legacy_upload_root=legacy_uploads,
        target_upload_root=target_uploads,
        target_database_url=target_url,
    )

    assert report["status"] == "migrated"
    with target_engine.connect() as connection:
        migrated = connection.execute(
            sa.select(Base.metadata.tables["users"])
        ).mappings().one()
    assert migrated["email"] == "legacy@example.com"
    assert migrated["reader_preferences"] == {}


def test_legacy_migration_accepts_upload_already_in_target_volume(
    tmp_path: Path,
) -> None:
    legacy_database = tmp_path / "legacy.db"
    legacy_uploads = tmp_path / "legacy-uploads"
    target_uploads = tmp_path / "target-uploads"
    legacy_uploads.mkdir()
    with sa.create_engine(f"sqlite:///{legacy_database.as_posix()}").begin():
        pass

    target_database = tmp_path / "target.db"
    target_url = f"sqlite:///{target_database.as_posix()}"
    target_engine = sa.create_engine(target_url)
    Base.metadata.create_all(target_engine)
    users = Base.metadata.tables["users"]
    book_imports = Base.metadata.tables["book_imports"]
    stored_path = "/data/uploads/reader/existing.epub"
    with target_engine.begin() as connection:
        connection.execute(
            users.insert(),
            {
                "id": "reader",
                "email": "reader@example.com",
                "password_hash": "hash",
                "display_name": "Reader",
            },
        )
        connection.execute(
            book_imports.insert(),
            {
                "id": "existing-import",
                "user_id": "reader",
                "original_name": "existing.epub",
                "stored_path": stored_path,
                "source_format": "epub",
                "size_bytes": 7,
                "content_hash": "hash",
                "status": "completed",
            },
        )

    target_file = target_uploads / "reader" / "existing.epub"
    target_file.parent.mkdir(parents=True)
    target_file.write_bytes(b"content")

    report = migrate_legacy_data(
        legacy_database=legacy_database,
        legacy_upload_root=legacy_uploads,
        target_upload_root=target_uploads,
        target_database_url=target_url,
    )

    assert report["status"] == "target_not_empty"
    assert report["copied_uploads"] == 0
    assert report["missing_uploads"] == []
    with target_engine.connect() as connection:
        migrated_path = connection.scalar(
            sa.select(book_imports.c.stored_path).where(
                book_imports.c.id == "existing-import"
            )
        )
    assert migrated_path == target_file.as_posix()
