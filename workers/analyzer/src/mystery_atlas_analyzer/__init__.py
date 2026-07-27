"""Mystery Atlas whole-book analysis module."""

from .contracts import BookAnalysis, BookInput, SourceChapter
from .pipeline import ANALYSIS_STAGES, PipelineConfig, analyze_book
from .runner import run_analysis_job

__all__ = [
    "ANALYSIS_STAGES",
    "BookAnalysis",
    "BookInput",
    "PipelineConfig",
    "SourceChapter",
    "analyze_book",
    "run_analysis_job",
]
