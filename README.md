---
title: Dataset Explorer
emoji: 📊
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 6.28.0
python_version: 3.12.12
app_file: app.py
short_description: Ask evidence-backed questions about uploaded tabular datasets.
---

# Dataset Explorer

Upload a CSV, TSV, Excel, JSON, or Parquet file and ask questions about it. Gemini chooses from
the available MCP analysis tools; Pandas computes the results. The application stores each
session's analysis state, evidence, and tool cache in SQLite.

## Run locally

```powershell
python -m pip install -e ".[dev]"
python app.py
```

Set `GEMINI_API_KEY` in the environment or a local `.env` file before asking questions. You can
upload and preview a dataset without the key. The legacy FastAPI interface remains available
through `uvicorn web_app:app --reload`, and the terminal client through `python mcp_client.py`.

Run tests with `python -m pytest -q`.

## Hugging Face Spaces

The repository includes Gradio Space metadata in this README, the `app.py` entry point, and
`requirements.txt`. Add `GEMINI_API_KEY` in the Space's **Settings → Secrets**; never commit it.
The Space uses temporary storage, so uploaded files and sessions disappear when it restarts.

As of September 2026, a standard Gradio Space requires a paid Hugging Face plan. A personal
account with a verified email and more than 30 days of account history may create up to two
free Gradio ZeroGPU Spaces. Choose **ZeroGPU** hardware when creating the Space. This app uses
CPU and the Gemini API, so it does not request GPU time. Check current eligibility in the
[Hugging Face Spaces documentation](https://huggingface.co/docs/hub/spaces-overview).

## Render

`render.yaml` deploys the existing FastAPI interface on Render's free web service.
Connect the GitHub repository as a Blueprint and provide `GEMINI_API_KEY` when prompted.
The free instance also uses temporary storage, so uploaded datasets and sessions may be
cleared after a restart or redeploy.

## ChatGPT / Remote MCP

The existing FastAPI service also serves Streamable HTTP at **`/mcp`**. ChatGPT
orchestrates these tools directly, without calling Gemini; the web/Gradio workflows
and `python mcp_server.py` stdio entrypoint remain available.

```powershell
python -m pip install -e ".[dev]"
python -m uvicorn web_app:app --host 127.0.0.1 --port 8000
```

Connect to `http://localhost:8000/mcp` using Streamable HTTP in
`npx @modelcontextprotocol/inspector`, or list tools from its CLI:

```powershell
npx @modelcontextprotocol/inspector --cli http://localhost:8000/mcp --transport http --method tools/list
```

`ingest_dataset` accepts `file: {download_url, file_id, mime_type?, file_name?}`,
advertised through [`_meta["openai/fileParams"]`](https://developers.openai.com/plugins/reference).
It downloads the ChatGPT file, reuses the shared ingestion/hash/schema pipeline, and
returns `dataset_id`, filename, row/column counts and schema. All ten analysis tools
use `dataset_id`; no remote tool accepts or returns a server filesystem path.
In Inspector, call ingestion with a direct public HTTPS dataset URL, a test `file_id`
and its filename, then call `dataset_shape` with the returned ID.

Downloads allow public HTTPS destinations on port 443 only, pin the validated IP
while verifying the TLS hostname, reject redirects, and enforce the 25 MB limit
during streaming. Socket operations time out after 10 seconds; the download loop
also checks a 60-second budget. Missing filenames are inferred only from recognized
MIME types; otherwise provide the filename. Temporary signed URLs are not persisted.

Render continues using `pip install .` and the unchanged start command:
`uvicorn web_app:app --host 0.0.0.0 --port $PORT`. After deploying these changes to
the existing service, use **`https://mcp-dataset-explorer.onrender.com/mcp`**.
Check the service's **Settings → Build & Deploy → Auto-Deploy**; if disabled, deploy
the updated connected branch through **Manual Deploy → Deploy latest commit**.
Render supplies TLS and `RENDER_EXTERNAL_HOSTNAME`, which is explicitly allowed
by the MCP Host/Origin checks. For a custom domain, set comma-separated
`MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS` (origins include `https://`).
The SDK requirement is now `mcp[cli]>=1.30.0,<2.0.0`, the tested v1 API supporting
tool metadata, transport security, and a bounded incoming request body; no v2 migration.

In ChatGPT, enable Developer Mode where available, create a private MCP connection
using the HTTPS URL and **No authentication**, then enable it in a chat and attach
a dataset. Ask ChatGPT to ingest it and reuse its ID for analysis. See the official
[connection instructions](https://developers.openai.com/plugins/deploy/connect-chatgpt)
for the controls available to your account. Refresh the connection's tool list after
server updates. The local HTTP address cannot be reached directly by hosted ChatGPT.

This is an **unauthenticated personal/testing endpoint**, not a multi-user access-control
system: anyone able to reach it can ingest files, and anyone holding a dataset ID can
analyze that dataset. A private ChatGPT connection does not make the server private.
Uploads and SQLite share `DATA_DIR` (default `.data`), allowing a persistent disk later.
On [Render Free](https://render.com/docs/free), storage is temporary: restart, spin-down
or redeployment may invalidate IDs. Re-upload the dataset to recover. Cold starts may
require retrying a connection. End-to-end ChatGPT attachment delivery requires a live
deployment and a test in your ChatGPT account; local tests mock the temporary download.

## Analysis tools

- Dataset overview, shape, and statistical summary
- Column and target inspection
- Missing values, duplicates, correlations, and outliers
- Target relationship screening with Pearson correlation, eta squared, or Cramer's V

Gemini interprets the question and selects tools. The MCP server returns statistics; the
application stores those results as evidence and asks Gemini for a cited explanation. Per
question, the agent makes at most four tool calls.

## Limits

Uploads are capped at 25 MB. Excel loading currently reads the first worksheet. This is an
exploratory analysis tool and does not establish causal effects or train ML models.
