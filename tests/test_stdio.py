"""Exercise the installed command over its real JSON-RPC stdio transport."""

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path


TOOLS = {
    "get_dataset_overview", "dataset_shape", "dataset_statistical_summary",
    "inspect_Column", "analyze_target", "duplicate_finder",
    "analyze_missing_values", "find_correlations", "detect_outliers",
    "screen_target_relationships",
}


def test_stdio_initialization_discovery_and_analysis(tmp_path):
    executable = Path(sys.executable).with_name(
        "dataset-explorer-mcp.exe" if os.name == "nt" else "dataset-explorer-mcp"
    )
    assert executable.is_file(), "Install the package before running this test."
    dataset = tmp_path / "sample.csv"
    dataset.write_text("score,double,group\n1,2,A\n2,4,A\n3,6,B\n3,6,B\n,8,B\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("GEMINI_", "RENDER_")) and key != "PYTHONPATH"}
    lines = queue.Queue()

    def reject_constant(value):
        raise ValueError(f"Non-JSON value on stdout: {value}")

    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as diagnostics:
        process = subprocess.Popen(
            [str(executable)], cwd=tmp_path, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=diagnostics,
            text=True, encoding="utf-8",
        )

        def read_stdout():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()

        def send(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def request(identifier, method, params=None):
            send({"jsonrpc": "2.0", "id": identifier, "method": method,
                  "params": params or {}})
            while True:
                line = lines.get(timeout=30)
                assert line is not None, "Server stopped before responding."
                response = json.loads(line, parse_constant=reject_constant)
                assert response["jsonrpc"] == "2.0"
                if response.get("id") == identifier:
                    assert "error" not in response, response
                    return response["result"]

        try:
            initialized = request(1, "initialize", {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "dataset-explorer-test", "version": "1.0"},
            })
            assert initialized["serverInfo"]["name"] == "DatasetExplorer"
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            discovered = request(2, "tools/list")
            assert {tool["name"] for tool in discovered["tools"]} == TOOLS
            arguments = {"path": str(dataset)}
            results = {}
            for identifier, name in enumerate(sorted(TOOLS), start=3):
                extra = {}
                if name == "inspect_Column":
                    extra["col_name"] = "score"
                elif name == "analyze_target":
                    extra["target_name"] = "score"
                elif name == "screen_target_relationships":
                    extra["target"] = "score"
                result = request(identifier, "tools/call", {
                    "name": name, "arguments": {**arguments, **extra},
                })
                assert not result.get("isError"), result
                results[name] = json.loads(
                    result["content"][0]["text"], parse_constant=reject_constant
                )
            assert results["dataset_shape"] == {"rows": 5, "columns": 3}
            assert results["dataset_statistical_summary"]["mean"]["score"] == 2.25
            assert results["duplicate_finder"]["duplicate_rows"] == 1
            assert results["analyze_missing_values"]["details"]["score"]["missing_count"] == 1
            assert results["find_correlations"]["strong_correlations"][0]["Correlation"] == 1.0
            resources = request(20, "resources/list")
            assert resources["resources"][0]["uri"] == "dataset://guide"
            guide = request(21, "resources/read", {"uri": "dataset://guide"})
            assert "Supported formats" in guide["contents"][0]["text"]
            prompts = request(22, "prompts/list")
            assert prompts["prompts"][0]["name"] == "explore_dataset"
            prompt = request(23, "prompts/get", {
                "name": "explore_dataset", "arguments": arguments,
            })
            assert str(dataset) in prompt["messages"][0]["content"]["text"]
            failed = request(24, "tools/call", {
                "name": "dataset_shape", "arguments": {"path": str(tmp_path / "missing.csv")},
            })
            assert failed["isError"] is True
            # The error is an MCP result; logging still goes to stderr.
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdout.close()
        assert process.returncode == 0
        while not lines.empty():
            line = lines.get_nowait()
            if line is not None:
                json.loads(line, parse_constant=reject_constant)


def test_installed_module_starts_from_another_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mcp_server", "--version"], cwd=tmp_path,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "0.2.1" in result.stdout
