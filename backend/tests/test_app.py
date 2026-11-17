from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


def test_health_without_ai_credentials():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_health_is_clear_without_database_configuration(monkeypatch):
    from app.db import session

    monkeypatch.setattr(session, "get_settings", lambda: Settings(database_url=None))
    with TestClient(app) as client:
        response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json()["checks"]["connectivity"] is False
    assert "DATABASE_URL" in response.json()["message"]


def test_database_backed_route_reports_missing_database_configuration(monkeypatch):
    from app.db import session

    monkeypatch.setattr(session, "get_settings", lambda: Settings(database_url=None))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ingest",
            json={"source_type": "note", "content": "Test note"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_database_diagnostic_does_not_return_credentials(monkeypatch):
    from app.db import session

    secret = "private-test-password"
    monkeypatch.setattr(
        session,
        "get_settings",
        lambda: Settings(database_url=f"postgresql+asyncpg://user:{secret}@127.0.0.1:1/database"),
    )
    with TestClient(app) as client:
        response = client.get("/health/db")
    assert response.status_code == 503
    assert secret not in response.text
    assert "Could not connect to PostgreSQL" in response.json()["message"]
