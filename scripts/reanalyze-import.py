from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
from pathlib import Path
import sys

from sqlalchemy import delete, select, update

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "workers" / "analyzer" / "src"))

from mystery_atlas_analyzer.runner import run_analysis_job  # noqa: E402
from mystery_atlas_analyzer.settings import AnalyzerSettings  # noqa: E402
from mystery_atlas_api.database import SessionLocal  # noqa: E402
from mystery_atlas_api.models import (  # noqa: E402
    AnalysisJob,
    BookImport,
    Chapter,
    Work,
)
from mystery_atlas_api.parsers import parse_book  # noqa: E402


def reparse_import(import_id: str) -> str:
    with SessionLocal() as session:
        book_import = session.get(BookImport, import_id)
        if book_import is None:
            raise LookupError(f"import {import_id} does not exist")
        if not book_import.work_id or not book_import.edition_id:
            raise ValueError(f"import {import_id} has not been finalized")

        parsed = parse_book(
            Path(book_import.stored_path),
            book_import.source_format,
            book_import.original_name,
        )
        if not parsed.chapters:
            raise ValueError("source parser returned no mainline chapters")

        session.execute(
            delete(Chapter).where(Chapter.edition_id == book_import.edition_id)
        )
        for index, item in enumerate(parsed.chapters):
            locator = dict(item.get("source_locator") or {})
            locator.update({"import_id": book_import.id, "index": index})
            text = str(item.get("text") or "")
            session.add(
                Chapter(
                    edition_id=book_import.edition_id,
                    number=int(item.get("number", index + 1)),
                    title=str(item.get("title") or "")[:300],
                    source_locator=locator,
                    text_fingerprint=hashlib.sha256(text.encode()).hexdigest(),
                )
            )

        book_import.chapters = parsed.chapters
        book_import.chapter_count = len(parsed.chapters)
        book_import.preview = parsed.preview
        book_import.stage = "ready_for_analysis"
        book_import.status = "completed"
        book_import.error = None

        work = session.scalar(select(Work).where(Work.id == book_import.work_id))
        if work is None:
            raise LookupError(f"work {book_import.work_id} does not exist")
        work.status = "analyzing"
        work.analysis_progress = 0

        session.execute(
            update(AnalysisJob)
            .where(
                AnalysisJob.work_id == book_import.work_id,
                AnalysisJob.status.in_(("queued", "running")),
            )
            .values(
                status="failed",
                stage="superseded",
                progress=0,
                error="superseded by a newer full reanalysis",
            )
        )
        job = AnalysisJob(
            work_id=book_import.work_id,
            edition_id=book_import.edition_id,
            track="full",
            stage="source_validation",
            status="queued",
            progress=0,
        )
        session.add(job)
        session.commit()
        return job.id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reparse a finalized import and replace its full AI analysis."
    )
    parser.add_argument("import_id")
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=None,
        help="Override concurrent model requests for this repair run.",
    )
    args = parser.parse_args()

    job_id = reparse_import(args.import_id)
    print(f"reparsed import; analysis job={job_id}", flush=True)
    settings = AnalyzerSettings.from_env()
    if args.max_concurrency is not None:
        settings = replace(
            settings,
            max_concurrency=max(1, args.max_concurrency),
        )
    result = run_analysis_job(job_id, settings=settings)
    print(
        "analysis completed; "
        f"removed_existing={result['persistence']['removed_existing']}; "
        f"people={result['persistence']['people']}; "
        f"evidence={result['persistence']['evidence']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
