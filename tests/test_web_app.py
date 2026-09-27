from fastapi.testclient import TestClient

from web_app import app


def test_health_and_upload_flow():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200

        files = {"file": ("sample.csv", b"score,group\n10,A\n20,B\n", "text/csv")}
        upload = client.post("/api/datasets", files=files)
        assert upload.status_code == 200
        dataset = upload.json()
        assert dataset["row_count"] == 2
        assert dataset["column_count"] == 2

        session = client.post("/api/sessions", json={"dataset_id": dataset["id"]})
        assert session.status_code == 200
        assert session.json()["state"]["status"] == "new"
