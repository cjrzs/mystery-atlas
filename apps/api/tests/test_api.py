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
    assert parsed.json()["stage"] == "awaiting_confirmation"

    finalized = client.post(
        f"/api/v1/imports/{import_id}/finalize",
        json={
            "title": "雾港测试",
            "author": "测试作者",
            "publisher": "测试出版社",
            "translator": None,
            "isbn": "978-7-0000-0000-1",
            "visibility": "public",
            "rights_confirmed": True,
        },
    )
    assert finalized.status_code == 200
    assert finalized.json()["visibility"] == "public"
    assert finalized.json()["work_id"]
    assert finalized.json()["edition_id"]

    duplicate_upload = client.post(
        "/api/v1/imports",
        files={"file": ("雾港重复.txt", content.encode("utf-8"), "text/plain")},
    )
    assert duplicate_upload.status_code == 202
    duplicate = client.post(
        f"/api/v1/imports/{duplicate_upload.json()['id']}/finalize",
        json={
            "title": "雾港测试",
            "author": "测试作者",
            "publisher": "测试出版社",
            "translator": None,
            "isbn": "978-7-0000-0000-1",
            "visibility": "private",
            "rights_confirmed": False,
        },
    )
    assert duplicate.status_code == 409

    works = client.get("/api/v1/works")
    uploaded = next(item for item in works.json() if item["title"] == "雾港测试")
    reader = client.get(f"/api/v1/works/{uploaded['slug']}/reader")
    assert reader.status_code == 200
    assert len(reader.json()["chapters"]) == 2
    assert "沈砚" in reader.json()["chapters"][0]["text"]

    library = client.get("/api/v1/library")
    assert library.status_code == 200
    assert any(item["title"] == "雾港测试" for item in library.json())

    feedback = client.post(
        "/api/v1/feedback",
        json={
            "work_id": finalized.json()["work_id"],
            "edition_id": finalized.json()["edition_id"],
            "entity_type": "relation",
            "chapter": 1,
            "content": "人物关系的章节位置需要修正。",
        },
    )
    assert feedback.status_code == 201
    resolved = client.patch(
        f"/api/v1/maintenance/feedback/{feedback.json()['id']}",
        json={
            "status": "resolved",
            "resolution": "已修正章节位置。",
            "change_summary": "修正人物关系首次出现章节",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_admin_route_requires_session() -> None:
    with TestClient(app) as anonymous:
        response = anonymous.get("/api/v1/admin/dashboard")
        assert response.status_code == 401
