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
