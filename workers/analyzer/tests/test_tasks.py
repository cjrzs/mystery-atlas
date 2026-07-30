from threading import Thread

from mystery_atlas_analyzer import tasks
from mystery_atlas_analyzer.contracts import AnalysisProgress


def test_analyze_edition_passes_task_id_to_threaded_progress_updates(
    monkeypatch,
) -> None:
    reported_task_ids: list[str | None] = []

    def update_state(
        *,
        task_id: str | None = None,
        state: str,
        meta: dict,
    ) -> None:
        reported_task_ids.append(task_id)

    def run_analysis_job(job_id: str, *, on_progress) -> dict:
        thread = Thread(
            target=on_progress,
            args=(
                AnalysisProgress(
                    stage="chapter_synthesis",
                    progress=43,
                    detail="checkpoint saved",
                ),
            ),
        )
        thread.start()
        thread.join()
        return {"job_id": job_id}

    monkeypatch.setattr(tasks.analyze_edition, "update_state", update_state)
    monkeypatch.setattr(tasks, "run_analysis_job", run_analysis_job)
    tasks.analyze_edition.push_request(id="celery-task-id")
    try:
        tasks.analyze_edition.run("analysis-job-id")
    finally:
        tasks.analyze_edition.pop_request()

    assert reported_task_ids == ["celery-task-id"]
