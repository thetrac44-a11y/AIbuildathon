from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"


def test_sitemap_has_10_screens_and_3_roles():
    response = client.get("/api/meta/sitemap")
    assert response.status_code == 200
    data = response.json()
    assert data["total_screens"] == 10
    assert data["roles"] == ["employee", "manager", "hr"]

    screens_by_id = {s["id"]: s for s in data["screens"]}
    assert "employee" not in screens_by_id["reports"]["allowed_roles"]
    assert screens_by_id["import"]["allowed_roles"] == ["hr"]
    assert screens_by_id["accounts"]["allowed_roles"] == ["hr"]


def test_business_constants_from_spec():
    assert settings.work_start_time == "08:30:00"
    assert settings.work_end_time == "17:30:00"
    assert settings.standard_work_hours == 8.0
    assert settings.late_grace_minutes == 5
    assert settings.ai_query_timeout_seconds == 3
    assert settings.ai_query_max_rows == 200
