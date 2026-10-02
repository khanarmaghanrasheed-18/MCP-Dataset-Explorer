"""ChatGPT-facing tools; filesystem paths remain inside the trusted server."""

import http.client
import ipaddress
import math
import os
import re
import socket
import ssl
import time
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any
from urllib.parse import urlsplit

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

import mcp_server as analysis
from dataset_upload import MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS
from dataset_upload import ingest_dataset as register_dataset
from state_store import StateStore


DOWNLOAD_TIMEOUT = 10
DOWNLOAD_DEADLINE = 60
MIME_EXTENSIONS = {
    "text/csv": ".csv", "text/tab-separated-values": ".tsv",
    "application/json": ".json", "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.apache.parquet": ".parquet", "application/x-parquet": ".parquet",
}


class ChatGPTFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    download_url: str = Field(min_length=1, max_length=16384)
    file_id: str = Field(min_length=1, max_length=512)
    mime_type: str = ""
    file_name: str = ""


def safe_filename(file: ChatGPTFile) -> str:
    # Handle both Windows and POSIX separators regardless of the server OS.
    name = file.file_name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w. -]", "_", name).strip(" .")
    if not name:
        extension = MIME_EXTENSIONS.get(file.mime_type.split(";", 1)[0].lower())
        if not extension:
            raise ToolError("A supported filename or recognized dataset MIME type is required.")
        name = "dataset" + extension
    extension = Path(name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ToolError("Unsupported file type. Use CSV, TSV, XLS/XLSX, JSON, or Parquet.")
    return name[:180 - len(extension)] + extension if len(name) > 180 else name


def validate_download_url(url: str) -> tuple[str, str, str]:
    """Resolve once, reject nonpublic addresses, and return a pinned destination."""
    try:
        if any(ord(char) <= 32 or ord(char) == 127 for char in url):
            raise ValueError
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or parts.fragment or "\\" in url):
            raise ValueError
        host = parts.hostname.encode("idna").decode("ascii")
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = [record[4][0] for record in addresses]
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        return host, ips[0], target
    except (ValueError, OSError, UnicodeError):
        raise ToolError("Download URL must use HTTPS on port 443 and resolve to a public address.") from None


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Keep TLS hostname verification while connecting to the validated IP only."""

    def __init__(self, host: str, address: str):
        super().__init__(host, timeout=DOWNLOAD_TIMEOUT, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw_socket = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except BaseException:
            raw_socket.close()
            raise


@contextmanager
def downloaded_file(url: str):
    """Bounded streaming download. Redirects and compressed responses are rejected."""
    started = time.monotonic()
    host, address, target = validate_download_url(url)
    connection = PinnedHTTPSConnection(host, address)
    try:
        connection.request("GET", target, headers={"Accept-Encoding": "identity"})
        with connection.getresponse() as response:
            if response.status != 200:
                raise ToolError("File download failed or redirected. Supply a fresh direct download URL.")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ToolError("Compressed HTTP responses are not supported.")
            length = response.getheader("Content-Length")
            if length is not None and int(length) > MAX_UPLOAD_BYTES:
                raise ToolError("Dataset exceeds the 25 MB upload limit.")
            with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as source:
                total = 0
                while True:
                    if time.monotonic() - started > DOWNLOAD_DEADLINE:
                        raise ToolError("File download timed out. Try again with a fresh file URL.")
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise ToolError("Dataset exceeds the 25 MB upload limit.")
                    source.write(chunk)
                if length is not None and total != int(length):
                    raise ToolError("File download was incomplete. Try again with a fresh file URL.")
                source.seek(0)
                yield source
    finally:
        connection.close()


def transport_security() -> TransportSecuritySettings:
    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*"]
    origins = ["http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*", "https://chatgpt.com"]
    render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_host:
        hosts.append(render_host)
        origins.append("https://" + render_host)
    hosts.extend(value.strip() for value in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if value.strip())
    origins.extend(value.strip() for value in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if value.strip())
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins,
    )


def json_safe(value: Any) -> Any:
    """Undefined Pandas statistics must be JSON null, never NaN/Infinity."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def create_remote_mcp(store: StateStore, upload_dir: Path) -> FastMCP:
    server = FastMCP(
        "Dataset Explorer",
        instructions=(
            "Perform deterministic exploratory analysis of tabular data. Ingest a supplied "
            "file first, then reuse its dataset_id. Use these tools for statistical claims; "
            "do not estimate statistics a tool can compute or invent values absent from results. "
            "Exploratory associations do not establish causation. If a dataset has expired, "
            "ask the user to upload it again. No Gemini calls are made by these tools."
        ),
        stateless_http=True, json_response=True,
        transport_security=transport_security(), max_request_body_size=64 * 1024,
    )
    readonly = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    def ingest(file: ChatGPTFile) -> dict[str, Any]:
        try:
            filename = safe_filename(file)
            with downloaded_file(file.download_url) as source:
                dataset, _ = register_dataset(source, filename, store, upload_dir)
            return {
                "dataset_id": dataset["id"], "filename": dataset["filename"],
                "rows": dataset["row_count"], "columns": dataset["column_count"],
                "schema": dataset["schema"],
            }
        except ToolError:
            raise
        except Exception:
            raise ToolError("Could not download or read the dataset. Check its format and upload it again.") from None

    @server.tool(
        meta={"openai/fileParams": ["file"]},
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                    openWorldHint=True, idempotentHint=False),
    )
    async def ingest_dataset(file: ChatGPTFile) -> dict[str, Any]:
        """Ingest a ChatGPT-uploaded CSV, TSV, Excel, JSON or Parquet (25 MB maximum).
        Call first for each new file, then reuse the returned dataset_id for analysis.
        Creates temporary server files/state; optional filename can be inferred from MIME type.
        """
        return await anyio.to_thread.run_sync(ingest, file)

    def run_analysis(function, dataset_id: str, *args) -> dict[str, Any]:
        try:
            dataset = store.get_dataset(dataset_id)
            if dataset is None:
                raise ToolError("Unknown dataset_id. Ingest the dataset first, or upload it again after a restart.")
            path = Path(dataset["stored_path"])
            if not path.is_file():
                raise ToolError("Dataset is no longer available. Upload it again.")
            result = function(str(path), *args)
            if result is None:
                return {"error": "This column type is not supported by this analysis."}
            return json_safe(result)
        except ToolError:
            raise
        except Exception:
            raise ToolError("Dataset analysis failed. Check the requested columns or upload the dataset again.") from None

    async def run(function, dataset_id, *args):
        return await anyio.to_thread.run_sync(partial(run_analysis, function, dataset_id, *args))

    @server.tool(annotations=readonly)
    async def get_dataset_overview(dataset_id: str) -> dict[str, Any]:
        """Get column names, data types, numeric/categorical classification and missing counts.
        Use for an initial understanding of a previously ingested dataset.
        """
        return await run(analysis.get_dataset_overview, dataset_id)

    @server.tool(annotations=readonly)
    async def dataset_shape(dataset_id: str) -> dict[str, Any]:
        """Compute the number of rows and columns in an ingested dataset."""
        return await run(analysis.get_dataset_shape, dataset_id)

    @server.tool(annotations=readonly)
    async def dataset_statistical_summary(dataset_id: str) -> dict[str, Any]:
        """Compute the mean and median of every numerical column."""
        return await run(analysis.get_dataset_statistical_summary, dataset_id)

    @server.tool(annotations=readonly)
    async def inspect_column(dataset_id: str, col_name: str) -> dict[str, Any]:
        """Inspect one column's type, missing/unique counts and numeric or category summary."""
        return await run(analysis.inspect_column, dataset_id, col_name)

    @server.tool(annotations=readonly)
    async def analyze_target(dataset_id: str, target_name: str) -> dict[str, Any]:
        """Summarize a user-selected target and heuristically classify the prediction task."""
        return await run(analysis.analyze_target, dataset_id, target_name)

    @server.tool(annotations=readonly)
    async def duplicate_finder(dataset_id: str) -> dict[str, Any]:
        """Count duplicate rows, report their percentage and show up to ten examples."""
        return await run(analysis.find_duplicated_data, dataset_id)

    @server.tool(annotations=readonly)
    async def analyze_missing_values(dataset_id: str) -> dict[str, Any]:
        """Locate missing values and compute per-column counts and percentages."""
        return await run(analysis.analyze_missing_values, dataset_id)

    @server.tool(annotations=readonly)
    async def find_correlations(dataset_id: str, threshold: float = Field(default=0.8, ge=0, le=1)) -> dict[str, Any]:
        """Find numerical feature pairs with absolute Pearson correlation at least threshold.
        Use screen_target_relationships for associations involving categorical variables.
        """
        return await run(analysis.find_correlations, dataset_id, threshold)

    @server.tool(annotations=readonly)
    async def detect_outliers(dataset_id: str) -> dict[str, Any]:
        """Detect unusual numerical observations using the 1.5-times-IQR rule."""
        return await run(analysis.detect_outliers, dataset_id)

    @server.tool(annotations=readonly)
    async def screen_target_relationships(dataset_id: str, target: str) -> dict[str, Any]:
        """Screen features associated with the user's chosen target, selecting Pearson,
        eta squared or Cramer's V for numerical/categorical types. Does not establish causation.
        """
        return await run(analysis.screen_target_relationships, dataset_id, target)

    return server
