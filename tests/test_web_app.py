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

        # Exercise the actual parent lifespan and mount alongside the original UI.
        assert client.get("/").status_code == 200
        headers = {"Accept": "application/json, text/event-stream", "Host": "localhost"}
        response = client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        assert response.status_code == 200
        assert not response.history
        assert len(response.json()["result"]["tools"]) == 11
        result = client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "dataset_shape", "arguments": {"dataset_id": dataset["id"]}},
        })
        assert result.json()["result"]["structuredContent"] == {"rows": 2, "columns": 2}
        # The original stdio session remains connected and exposes its path tools.
        stdio_tools = client.portal.call(app.state.agent.mcp_session.list_tools)
        assert any("path" in tool.inputSchema["properties"] for tool in stdio_tools.tools)
