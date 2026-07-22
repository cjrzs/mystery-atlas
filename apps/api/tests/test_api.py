from fastapi.testclient import TestClient

from mystery_atlas_api.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_graph_obeys_chapter_horizon() -> None:
    response = client.get("/api/v1/works/fog-harbor-clocktower/graph?through_chapter=2")
    assert response.status_code == 200
    payload = response.json()
    assert all(node["first_chapter"] <= 2 for node in payload["nodes"])
    assert all(edge["first_chapter"] <= 2 for edge in payload["edges"])


def test_unknown_work_returns_404() -> None:
    response = client.get("/api/v1/works/not-a-work")
    assert response.status_code == 404

