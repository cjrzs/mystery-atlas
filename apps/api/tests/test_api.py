import pytest
from fastapi.testclient import TestClient

from mystery_atlas_api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_graph_obeys_chapter_horizon(client: TestClient) -> None:
    response = client.get("/api/v1/works/fog-harbor-clocktower/graph?through_chapter=2")
    assert response.status_code == 200
    payload = response.json()
    assert all(node["first_chapter"] <= 2 for node in payload["nodes"])
    assert all(edge["first_chapter"] <= 2 for edge in payload["edges"])


def test_unknown_work_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/works/not-a-work")
    assert response.status_code == 404


def test_register_login_and_session_cookie(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "reader@example.com",
            "password": "strong-password-2026",
            "display_name": "测试读者",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "admin"
    assert response.cookies.get("mystery_atlas_session")

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "reader@example.com"

    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "reader@example.com", "password": "strong-password-2026"},
    )
    assert login.status_code == 200


def test_upload_and_parse_txt(client: TestClient) -> None:
    content = """第一章 雾港\n沈砚在夜里抵达钟楼。\n第二章 晚宴\n梁家众人围绕遗嘱争执。\n"""
    response = client.post(
        "/api/v1/imports",
        files={"file": ("雾港测试.txt", content.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 202
    import_id = response.json()["id"]

    parsed = client.get(f"/api/v1/imports/{import_id}")
    assert parsed.status_code == 200
    assert parsed.json()["status"] == "completed"
    assert parsed.json()["detected_title"] == "雾港测试"
    assert parsed.json()["chapter_count"] == 2


def test_admin_route_requires_session() -> None:
    with TestClient(app) as anonymous:
        response = anonymous.get("/api/v1/admin/review-queue")
        assert response.status_code == 401
