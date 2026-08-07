from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from aleph.core.config import Config, Secret
from api.database import Database
from api.jobs import JobStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Run every API test against an isolated durable store, never local data."""
    url = f"sqlite:///{tmp_path / 'api-test.db'}"
    config = replace(Config(), database_url=Secret(url))
    database = Database(url)
    store = JobStore(config=config, database=database)
    monkeypatch.setattr(api_main, "jobs", store)
    with TestClient(api_main.app) as test_client:
        yield test_client
    database.dispose()


def test_health_contract(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.0.0"


def test_upload_runs_warm_pipeline(client: TestClient) -> None:
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

    listing = client.get("/v1/analyses")
    assert listing.status_code == 200
    stored = next(item for item in listing.json()["analyses"] if item["id"] == job_id)
    assert stored["result_sha256"]
    assert stored["model"]["revision"] == "builtin"

    history = client.get(f"/v1/documents/{stored['document_record_id']}/analyses")
    assert history.status_code == 200
    assert any(item["id"] == job_id for item in history.json()["analyses"])


def test_rerun_is_a_new_append_only_version(client: TestClient) -> None:
    created = client.post(
        "/v1/analyses",
        files={"file": ("versioned.txt", b"A regulator shall publish data.", "text/plain")},
    ).json()
    original_id = created["id"]
    original = client.get(f"/v1/analyses/{original_id}/status").json()

    response = client.post(f"/v1/analyses/{original_id}/rerun")
    assert response.status_code == 202
    replacement_id = response.json()["id"]
    replacement = client.get(f"/v1/analyses/{replacement_id}/status").json()

    assert replacement_id != original_id
    assert replacement["supersedes_run_id"] == original_id
    assert replacement["state"] == "complete"
    original_result = client.get(f"/v1/analyses/{original_id}").json()
    replacement_result = client.get(f"/v1/analyses/{replacement_id}").json()
    assert (
        original_result["document"]["source"]["file_hash"]
        == replacement_result["document"]["source"]["file_hash"]
    )
    assert (
        client.get(f"/v1/analyses/{original_id}/status").json()["result_sha256"]
        == original["result_sha256"]
    )
