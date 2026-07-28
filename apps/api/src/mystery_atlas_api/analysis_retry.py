from __future__ import annotations

import re

from mystery_atlas_analyzer.contracts import AnalysisCheckpoint

from .models import AnalysisJob, BookImport, Edition, User, Work
from .parsers import EPUB_PARSER_VERSION


def can_manage_analysis(
    user: User | None,
    work: Work,
    edition: Edition,
) -> bool:
    if user is None:
        return False
    return user.role == "admin" or user.id in {
        work.owner_id,
        work.maintainer_id,
        edition.maintainer_id,
    }


def failed_stage(job: AnalysisJob) -> str:
    if job.stage != "failed":
        return job.stage
    match = re.match(r"([a-z_]+) failed\b", job.error or "")
    return match.group(1) if match else "failed"


def checkpoint_for_job(job: AnalysisJob) -> AnalysisCheckpoint:
    result_summary = job.result_summary if isinstance(job.result_summary, dict) else {}
    payload = result_summary.get("checkpoint")
    return (
        AnalysisCheckpoint.model_validate(payload)
        if isinstance(payload, dict)
        else AnalysisCheckpoint()
    )


def checkpoint_has_data(checkpoint: AnalysisCheckpoint) -> bool:
    return bool(
        checkpoint.chapters
        or checkpoint.parts
        or checkpoint.synthesis
        or checkpoint.reconciliation
    )


def can_retry_from_checkpoint(job: AnalysisJob) -> bool:
    if job.status not in {"failed", "waiting_configuration"}:
        return False
    stage = failed_stage(job)
    if stage in {
        "source_validation",
        "segment_analysis",
        "chapter_synthesis",
        "waiting_for_ai_configuration",
    }:
        return True

    checkpoint = checkpoint_for_job(job)
    if stage == "failed":
        return checkpoint_has_data(checkpoint)
    if stage == "book_synthesis":
        return bool(checkpoint.parts or checkpoint.chapters)
    if stage in {"evidence_verification", "full_book_reconciliation"}:
        return checkpoint.synthesis is not None
    if stage == "persistence":
        return checkpoint.reconciliation is not None
    return False


def can_restart_from_beginning(job: AnalysisJob) -> bool:
    if job.status not in {"failed", "waiting_configuration"}:
        return False
    if can_retry_from_checkpoint(job):
        return False
    return not checkpoint_has_data(checkpoint_for_job(job))


def should_reparse_source(
    job: AnalysisJob,
    book_import: BookImport | None,
) -> bool:
    if book_import is None or book_import.source_format != "epub":
        return False
    if book_import.parser_version != EPUB_PARSER_VERSION:
        return True
    if not book_import.structure_version:
        return True
    if failed_stage(job) == "source_validation":
        return True
    error = (job.error or "").casefold()
    return any(
        marker in error
        for marker in (
            "chapter structure",
            "parsed chapter",
            "章节结构",
            "目录定位",
        )
    )


def analysis_retry_hint(
    job: AnalysisJob | None,
    *,
    user: User | None,
    permitted: bool,
) -> str:
    if job is None or job.status not in {"failed", "waiting_configuration"}:
        return ""
    if user is None:
        return "请登录后由作品维护者重试。"
    if not permitted:
        return "只有作品所有者、维护者或管理员可以重试。"
    if can_restart_from_beginning(job):
        return "该旧任务没有阶段检查点，只能从头重新分析；确认后会重新消耗 Token。"
    if not can_retry_from_checkpoint(job):
        return "该任务没有可用的阶段检查点，无法在不重跑前置阶段的情况下恢复。"
    return ""
