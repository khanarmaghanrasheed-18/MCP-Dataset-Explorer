import asyncio
import hashlib
import io
import json
import socket

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

import mcp_server as analysis
import remote_mcp as remote
from dataset_upload import MAX_UPLOAD_BYTES, ingest_dataset
from state_store import StateStore


CSV = b"score,other,group\n10,20,A\n20,40,B\n30,60,A\n"


@pytest.fixture
def setup(tmp_path):
    store = StateStore(tmp_path / "state.db")
    uploads = tmp_path / "uploads"
    return remote.create_remote_mcp(store, uploads), store, uploads


def call(server, name, arguments):
    return asyncio.run(server.call_tool(name, arguments))[1]


def mock_download(monkeypatch, data=CSV, *, status=200, headers=None):
    instances = []

    class Response(io.BytesIO):
        def __init__(self):
            super().__init__(data)
            self.status = status

        def getheader(self, name, default=None):
            return (headers or {}).get(name, default)

    class Connection:
        def __init__(self, host, address):
            self.host, self.address = host, address
            self.closed = False
            instances.append(self)

        def request(self, method, target, headers):
            self.target = target
            assert method == "GET"
            assert headers["Accept-Encoding"] == "identity"

        def getresponse(self):
            return Response()

        def close(self):
            self.closed = True

    monkeypatch.setattr(remote, "PinnedHTTPSConnection", Connection)
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
    ])
    return instances


def descriptor(**kwargs):
    return {"download_url": "https://files.example/data?token=secret", "file_id": "file_test", **kwargs}


@pytest.mark.parametrize("filename,data", [("sample.csv", CSV), ("sample.json", b'[{"score":10},{"score":20}]')])
def test_ingestion(setup, monkeypatch, filename, data):
    server, store, uploads = setup
    connections = mock_download(monkeypatch, data)
    result = call(server, "ingest_dataset", {"file": descriptor(file_name=filename)})
    dataset = store.get_dataset(result["dataset_id"])
    assert result["rows"] in (2, 3)
    assert result["filename"] == filename
    assert dataset["file_hash"] == hashlib.sha256(data).hexdigest()
    assert "stored_path" not in json.dumps(result)
    assert str(uploads) not in json.dumps(result)
    assert connections[0].closed
    assert call(server, "dataset_shape", {"dataset_id": result["dataset_id"]})["rows"] == result["rows"]


@pytest.mark.parametrize("name", ["../../sample.csv", r"C:\private\sample.csv", r"..\..\sample.csv"])
def test_filename_sanitization(setup, monkeypatch, name):
    mock_download(monkeypatch)
    result = call(setup[0], "ingest_dataset", {"file": descriptor(file_name=name)})
    assert result["filename"] == "sample.csv"


def test_missing_filename(setup, monkeypatch):
    mock_download(monkeypatch)
    result = call(setup[0], "ingest_dataset", {"file": descriptor(mime_type="text/csv")})
    assert result["filename"] == "dataset.csv"
    with pytest.raises(ToolError, match="filename"):
        call(setup[0], "ingest_dataset", {"file": descriptor()})


def test_unsupported_extension_rejected_before_download(setup, monkeypatch):
    connections = mock_download(monkeypatch)
    with pytest.raises(ToolError, match="Unsupported file type"):
        call(setup[0], "ingest_dataset", {"file": descriptor(file_name="malware.exe")})
    assert not connections


@pytest.mark.parametrize("declared", [True, False])
def test_upload_limit(setup, monkeypatch, declared):
    headers = {"Content-Length": str(MAX_UPLOAD_BYTES + 1)} if declared else {}
    connections = mock_download(monkeypatch, b"x" * (MAX_UPLOAD_BYTES + 1), headers=headers)
    with pytest.raises(ToolError, match="25 MB"):
        call(setup[0], "ingest_dataset", {"file": descriptor(file_name="huge.csv")})
    assert connections[0].closed
    assert not setup[2].exists()


@pytest.mark.parametrize("url", [
    "http://example.com/a.csv", "file:///etc/passwd", "https://user:pass@example.com/a.csv",
    "https://example.com:8443/a.csv", "https://example.com/a\r\nInjected: header",
])
def test_bad_urls_rejected(url):
    with pytest.raises(ToolError, match="HTTPS"):
        remote.validate_download_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1"])
def test_private_dns_rejected(monkeypatch, address):
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)),
    ])
    with pytest.raises(ToolError, match="public address"):
        remote.validate_download_url("https://files.example/data")


def test_pinned_connection_keeps_tls_hostname(monkeypatch):
    seen = []
    raw = object()
    monkeypatch.setattr(remote.socket, "create_connection", lambda address, timeout: seen.append(address) or raw)

    class Context:
        def wrap_socket(self, sock, server_hostname):
            assert sock is raw
            seen.append(server_hostname)
            return raw

    connection = remote.PinnedHTTPSConnection("files.example", "93.184.216.34")
    connection._context = Context()
    connection.connect()
    assert seen == [("93.184.216.34", 443), "files.example"]


@pytest.mark.parametrize("status,headers,message", [
    (302, {"Location": "http://127.0.0.1/private"}, "redirected"),
    (200, {"Content-Encoding": "gzip"}, "Compressed"),
    (200, {"Content-Length": "9999"}, "incomplete"),
])
def test_bad_download_response(setup, monkeypatch, status, headers, message):
    connections = mock_download(monkeypatch, status=status, headers=headers)
    with pytest.raises(ToolError, match=message):
        call(setup[0], "ingest_dataset", {"file": descriptor(file_name="sample.csv")})
    assert connections[0].closed


def test_deadline(setup, monkeypatch):
    mock_download(monkeypatch)
    ticks = iter([0, remote.DOWNLOAD_DEADLINE + 1])
    monkeypatch.setattr(remote.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ToolError, match="timed out"):
        with remote.downloaded_file(descriptor()["download_url"]):
            pass


def test_errors_do_not_leak_paths_or_signed_urls(setup, monkeypatch):
    mock_download(monkeypatch)

    def fail(*args):
        raise OSError("C:/private/state.db https://files.example/?token=secret")

    monkeypatch.setattr(remote, "register_dataset", fail)
    with pytest.raises(ToolError) as error:
        call(setup[0], "ingest_dataset", {"file": descriptor(file_name="sample.csv")})
    assert "private" not in str(error.value)
    assert "secret" not in str(error.value)


ANALYSES = [
    ("get_dataset_overview", analysis.get_dataset_overview, {}),
    ("dataset_shape", analysis.get_dataset_shape, {}),
    ("dataset_statistical_summary", analysis.get_dataset_statistical_summary, {}),
    ("inspect_column", analysis.inspect_column, {"col_name": "score"}),
    ("analyze_target", analysis.analyze_target, {"target_name": "group"}),
    ("duplicate_finder", analysis.find_duplicated_data, {}),
    ("analyze_missing_values", analysis.analyze_missing_values, {}),
    ("find_correlations", analysis.find_correlations, {"threshold": 0.8}),
    ("detect_outliers", analysis.detect_outliers, {}),
    ("screen_target_relationships", analysis.screen_target_relationships, {"target": "group"}),
]


@pytest.mark.parametrize("name,function,arguments", ANALYSES)
def test_wrappers_match_existing_analysis(setup, name, function, arguments):
    server, store, uploads = setup
    dataset, _ = ingest_dataset(io.BytesIO(CSV), "sample.csv", store, uploads)
    result = call(server, name, {"dataset_id": dataset["id"], **arguments})
    assert result == function(dataset["stored_path"], **arguments)
    with pytest.raises(ToolError, match="Unknown dataset_id"):
        call(server, name, {"dataset_id": "../../iris.csv", **arguments})


def test_unavailable_dataset_and_nonfinite_statistics(setup):
    server, store, uploads = setup
    dataset, _ = ingest_dataset(io.BytesIO(b"value,blank\n1,\n"), "single.csv", store, uploads)
    result = call(server, "analyze_target", {"dataset_id": dataset["id"], "target_name": "value"})
    assert result["Standard Deviation"] is None
    json.dumps(result, allow_nan=False)
    from pathlib import Path
    Path(dataset["stored_path"]).unlink()
    with pytest.raises(ToolError, match="no longer available"):
        call(server, "dataset_shape", {"dataset_id": dataset["id"]})


def test_tool_schemas(setup):
    tools = asyncio.run(setup[0].list_tools())
    assert len(tools) == 11
    for tool in tools:
        properties = tool.inputSchema["properties"]
        assert "path" not in properties
        if tool.name == "ingest_dataset":
            assert tool.meta["openai/fileParams"] == ["file"]
            file_schema = tool.inputSchema["$defs"]["ChatGPTFile"]
            assert set(file_schema["required"]) == {"download_url", "file_id"}
            assert set(file_schema["properties"]) == {"download_url", "file_id", "mime_type", "file_name"}
            assert all(prop["type"] == "string" for prop in file_schema["properties"].values())
            assert tool.annotations.readOnlyHint is False
            assert tool.annotations.openWorldHint is True
        else:
            assert "dataset_id" in tool.inputSchema["required"]
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.openWorldHint is False
        assert tool.annotations.destructiveHint is False


def test_http_transport_and_host_security(setup, monkeypatch):
    server = setup[0]
    mock_download(monkeypatch)
    app = server.streamable_http_app()
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app, base_url="http://localhost") as client:
        def rpc(method, params=None):
            response = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
            })
            assert response.status_code == 200
            assert not response.history
            return response.json()["result"]

        result = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "test", "version": "1"}})
        assert result["serverInfo"]["name"] == "Dataset Explorer"
        assert len(rpc("tools/list")["tools"]) == 11
        result = rpc("tools/call", {"name": "ingest_dataset", "arguments": {
            "file": descriptor(file_name="sample.csv"),
        }})
        dataset_id = result["structuredContent"]["dataset_id"]
        result = rpc("tools/call", {"name": "dataset_shape", "arguments": {"dataset_id": dataset_id}})
        assert result["structuredContent"] == {"rows": 3, "columns": 3}
        assert client.post("/mcp", headers={**headers, "Host": "evil.example"}, json={}).status_code == 421
        assert client.post("/mcp", headers={**headers, "Origin": "https://evil.example"}, json={}).status_code == 403
        assert client.post("/mcp", headers=headers, content=b"x" * (64 * 1024 + 1)).status_code == 413


def test_render_hostname_allowlist(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "mcp-dataset-explorer.onrender.com")
    settings = remote.transport_security()
    assert settings.enable_dns_rebinding_protection
    assert "mcp-dataset-explorer.onrender.com" in settings.allowed_hosts
    assert "https://mcp-dataset-explorer.onrender.com" in settings.allowed_origins
