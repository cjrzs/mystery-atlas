from uuid import uuid4

from fastapi.testclient import TestClient

from mystery_atlas_api.database import SessionLocal
from mystery_atlas_api.main import app
from mystery_atlas_api.models import (
    AnalysisJob,
    ChapterSnapshot,
    Edition,
    Evidence,
    Person,
    Work,
)


def test_workbench_analysis_uses_selected_work_and_chapter_horizon() -> None:
    work_id = str(uuid4())
    edition_id = str(uuid4())
    slug = f"workbench-{uuid4().hex[:8]}"
    with TestClient(app) as client:
        with SessionLocal() as session:
            session.add(
                Work(
                    id=work_id,
                    slug=slug,
                    title="Selected Book",
                    author="Selected Author",
                    status="analyzing",
                    visibility="public",
                    analysis_progress=41,
                )
            )
            session.add(
                Edition(
                    id=edition_id,
                    work_id=work_id,
                    title="Selected Edition",
                    source_format="txt",
                    visibility="public",
                )
            )
            session.add_all(
                [
                    Person(
                        work_id=work_id,
                        canonical_name="Visible Person",
                        role="witness",
                        description="Visible description",
                        first_chapter=1,
                    ),
                    Person(
                        work_id=work_id,
                        canonical_name="Future Person",
                        role="suspect",
                        description="Future description",
                        first_chapter=4,
                    ),
                    Evidence(
                        work_id=work_id,
                        first_chapter=1,
                        title="Visible clue",
                        summary="Visible summary",
                        source_type="text",
                        status="confirmed",
                        citation={"excerpt": "Visible excerpt", "chapter": 1},
                    ),
                    Evidence(
                        work_id=work_id,
                        first_chapter=4,
                        title="Future clue",
                        summary="Future summary",
                        source_type="text",
                        status="confirmed",
                        citation={"excerpt": "Future excerpt", "chapter": 4},
                    ),
                    ChapterSnapshot(
                        work_id=work_id,
                        chapter=1,
                        graph_payload={},
                        timeline_payload=[
                            {
                                "chapter": 1,
                                "sequence": 1,
                                "summary": "Visible event",
                                "story_time": "night",
                                "narrative_time": "chapter 1",
                            },
                            {
                                "chapter": 4,
                                "sequence": 1,
                                "summary": "Future event",
                                "story_time": "later",
                                "narrative_time": "chapter 4",
                            },
                        ],
                        summary="Visible chapter summary",
                    ),
                    AnalysisJob(
                        work_id=work_id,
                        edition_id=edition_id,
                        track="full",
                        stage="segment_analysis",
                        status="running",
                        progress=41,
                    ),
                ]
            )
            session.commit()

        response = client.get(f"/api/v1/works/{slug}/analysis?through_chapter=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["work_id"] == work_id
    assert payload["work_slug"] == slug
    assert payload["status"] == "running"
    assert payload["progress"] == 41
    assert [item["name"] for item in payload["graph"]["nodes"]] == ["Visible Person"]
    assert [item["title"] for item in payload["evidence"]] == ["Visible clue"]
    assert [item["summary"] for item in payload["timeline"]] == ["Visible event"]
    assert [item["summary"] for item in payload["chapters"]] == [
        "Visible chapter summary"
    ]


def test_workbench_analysis_hides_internal_job_error() -> None:
    work_id = str(uuid4())
    edition_id = str(uuid4())
    slug = f"failed-workbench-{uuid4().hex[:8]}"
    internal_error = (
        "segment_analysis failed after 3 attempts: "
        "<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>"
    )
    with TestClient(app) as client:
        with SessionLocal() as session:
            session.add(
                Work(
                    id=work_id,
                    slug=slug,
                    title="Failed Book",
                    author="Selected Author",
                    status="analyzing",
                    visibility="public",
                )
            )
            session.add(
                Edition(
                    id=edition_id,
                    work_id=work_id,
                    title="Failed Edition",
                    source_format="txt",
                    visibility="public",
                )
            )
            session.add(
                AnalysisJob(
                    work_id=work_id,
                    edition_id=edition_id,
                    track="full",
                    stage="failed",
                    status="failed",
                    error=internal_error,
                )
            )
            session.commit()

        response = client.get(f"/api/v1/works/{slug}/analysis")

    assert response.status_code == 200
    assert response.json()["error"] == "暂时无法连接 AI 分析服务，请稍后重试。"
    assert "urlopen" not in response.text
    assert "SSL" not in response.text
