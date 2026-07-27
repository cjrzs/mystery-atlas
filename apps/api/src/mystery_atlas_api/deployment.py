from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import MetaData, create_engine, func, insert, select, update

from . import models as _models  # noqa: F401
from .config import get_settings
from .database import Base


def _sqlite_snapshot(source: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    target = Path(tempfile.gettempdir()) / "mystery-atlas-legacy-snapshot.db"
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(target) as target_connection:
            source_connection.backup(target_connection)
    return target


def _relative_upload_path(stored_path: str, user_id: str) -> Path:
    parts = [part for part in re.split(r"[\\/]+", stored_path) if part]
    lowered = [part.casefold() for part in parts]
    if "uploads" in lowered:
        relative = parts[lowered.index("uploads") + 1 :]
        if relative:
            return Path(*relative)
    return Path(user_id) / Path(stored_path).name


def _copy_legacy_uploads(
    target_connection,
    *,
    legacy_upload_root: Path,
    target_upload_root: Path,
) -> tuple[int, list[str]]:
    book_imports = Base.metadata.tables["book_imports"]
    rows = target_connection.execute(
        select(
            book_imports.c.id,
            book_imports.c.user_id,
            book_imports.c.stored_path,
            book_imports.c.status,
        )
    ).mappings()
    copied = 0
    missing: list[str] = []
    target_upload_root.mkdir(parents=True, exist_ok=True)
    for row in rows:
        relative = _relative_upload_path(row["stored_path"], row["user_id"])
        source = legacy_upload_root / relative
        target = target_upload_root / relative
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or target.stat().st_size != source.stat().st_size:
                shutil.copy2(source, target)
                copied += 1
            target_connection.execute(
                update(book_imports)
                .where(book_imports.c.id == row["id"])
                .values(stored_path=target.as_posix())
            )
        elif row["status"] == "completed":
            missing.append(row["id"])
    return copied, missing


def migrate_legacy_data(
    *,
    legacy_database: Path,
    legacy_upload_root: Path,
    target_upload_root: Path,
    target_database_url: str,
) -> dict[str, object]:
    if not legacy_database.is_file():
        return {
            "status": "no_legacy_database",
            "copied_rows": 0,
            "copied_uploads": 0,
            "missing_uploads": [],
            "tables": {},
        }

    snapshot = _sqlite_snapshot(legacy_database)
    source_engine = create_engine(f"sqlite:///{snapshot.as_posix()}")
    target_engine = create_engine(target_database_url, pool_pre_ping=True)
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)

    users = Base.metadata.tables["users"]
    works = Base.metadata.tables["works"]
    book_imports = Base.metadata.tables["book_imports"]
    with target_engine.begin() as target_connection:
        existing = sum(
            int(target_connection.scalar(select(func.count()).select_from(table)) or 0)
            for table in (users, works, book_imports)
        )
        if existing:
            copied_uploads, missing_uploads = _copy_legacy_uploads(
                target_connection,
                legacy_upload_root=legacy_upload_root,
                target_upload_root=target_upload_root,
            )
            return {
                "status": "target_not_empty",
                "copied_rows": 0,
                "copied_uploads": copied_uploads,
                "missing_uploads": missing_uploads,
                "tables": {},
            }

        copied_rows = 0
        table_counts: dict[str, int] = {}
        with source_engine.connect() as source_connection:
            for target_table in Base.metadata.sorted_tables:
                source_table = source_metadata.tables.get(target_table.name)
                if source_table is None:
                    continue
                shared_columns = [
                    column.name
                    for column in target_table.columns
                    if column.name in source_table.c
                ]
                rows = [
                    {name: row[name] for name in shared_columns}
                    for row in source_connection.execute(
                        select(*(source_table.c[name] for name in shared_columns))
                    ).mappings()
                ]
                if rows:
                    target_connection.execute(insert(target_table), rows)
                table_counts[target_table.name] = len(rows)
                copied_rows += len(rows)

        copied_uploads, missing_uploads = _copy_legacy_uploads(
            target_connection,
            legacy_upload_root=legacy_upload_root,
            target_upload_root=target_upload_root,
        )

    with target_engine.connect() as connection:
        for table_name, expected in table_counts.items():
            table = Base.metadata.tables[table_name]
            actual = int(connection.scalar(select(func.count()).select_from(table)) or 0)
            if actual != expected:
                raise RuntimeError(
                    f"migration validation failed for {table_name}: {actual} != {expected}"
                )

    return {
        "status": "migrated",
        "copied_rows": copied_rows,
        "copied_uploads": copied_uploads,
        "missing_uploads": missing_uploads,
        "tables": table_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate retained local data into Docker.")
    parser.add_argument("command", choices=["migrate-legacy"])
    parser.add_argument(
        "--legacy-database",
        type=Path,
        default=Path("/legacy/mystery-atlas.db"),
    )
    parser.add_argument(
        "--legacy-upload-root",
        type=Path,
        default=Path("/legacy/uploads"),
    )
    parser.add_argument(
        "--target-upload-root",
        type=Path,
        default=Path(get_settings().upload_dir),
    )
    arguments = parser.parse_args()
    report = migrate_legacy_data(
        legacy_database=arguments.legacy_database,
        legacy_upload_root=arguments.legacy_upload_root,
        target_upload_root=arguments.target_upload_root,
        target_database_url=get_settings().database_url,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["missing_uploads"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
