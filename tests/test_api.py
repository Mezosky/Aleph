from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_contract() -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.0.0"


def test_upload_runs_warm_pipeline() -> None:
    response = client.post(
        "/v1/analyses",
        files={"file": ("fixture.txt", b"The agency shall publish a report.", "text/plain")},
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    status = client.get(f"/v1/analyses/{job_id}/status")
    assert status.status_code == 200
    assert status.json()["state"] == "complete"
    result = client.get(f"/v1/analyses/{job_id}")
    assert result.status_code == 200
    assert result.json()["readiness"]["publishable"] is False
