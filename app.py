"""Gradio entry point for the Hugging Face Space."""

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import gradio as gr
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_service import AgentService
from dataset_upload import SUPPORTED_EXTENSIONS, ingest_dataset
from state_store import StateStore


load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = (
    Path(tempfile.gettempdir()) / "dataset-explorer"
    if os.getenv("SPACE_ID")
    else BASE_DIR / ".data"
)
DATA_DIR = Path(os.getenv("DATA_DIR", DEFAULT_DATA_DIR)).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
store = StateStore(DATA_DIR / "dataset_explorer.db")
logger = logging.getLogger(__name__)


def dataset_summary(dataset: dict[str, Any]) -> str:
    schema = dataset["schema"]
    numerical = len(schema["numerical_columns"])
    categorical = len(schema["categorical_columns"])
    return (
        f"### {dataset['filename']}\n"
        f"{dataset['row_count']:,} rows · {dataset['column_count']:,} columns · "
        f"{numerical} numerical · {categorical} categorical\n\n"
        "The first 10 rows are shown below. Ask a question to start the analysis."
    )


def handle_upload(file_path: str | None):
    if not file_path:
        raise gr.Error("Choose a dataset file first.")

    path = Path(file_path)
    try:
        with path.open("rb") as source:
            dataset, dataframe = ingest_dataset(source, path.name, store, UPLOAD_DIR)
        session = store.create_session(dataset)
    except ValueError as error:
        raise gr.Error(str(error)) from error
    except Exception as error:
        logger.exception("Dataset upload failed")
        raise gr.Error(f"The dataset could not be read: {error}") from error

    return (
        session["id"],
        dataset_summary(dataset),
        dataframe.head(10),
        [],
        session["state"],
        [],
    )


async def run_analysis(session_id: str, question: str) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(BASE_DIR / "mcp_server.py")],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            agent = AgentService(mcp_session, store)
            return await agent.ask(session_id, question)


async def handle_question(
    question: str,
    session_id: str | None,
    history: list[dict[str, str]] | None,
):
    question = (question or "").strip()
    if not session_id:
        raise gr.Error("Upload a dataset and start an analysis first.")
    if not question:
        raise gr.Error("Enter a question about the dataset.")
    if not os.getenv("GEMINI_API_KEY"):
        raise gr.Error("GEMINI_API_KEY is not configured for this Space.")

    try:
        result = await run_analysis(session_id, question)
    except (RuntimeError, ValueError) as error:
        raise gr.Error(str(error)) from error
    except Exception as error:
        logger.exception("Dataset analysis failed")
        raise gr.Error("Analysis failed. Check the Space logs for details.") from error

    updated_history = list(history or [])
    updated_history.extend([
        {"role": "user", "content": question},
        {"role": "assistant", "content": result["answer"]},
    ])
    return "", updated_history, result["state"], result["tool_calls"]


with gr.Blocks(title="Dataset Explorer") as demo:
    gr.Markdown(
        "# Dataset Explorer\n"
        "Upload a tabular dataset, then ask Gemini to investigate it with MCP analysis tools."
    )
    session_id = gr.State()

    with gr.Row():
        with gr.Column(scale=1):
            dataset_file = gr.File(
                label="Dataset",
                file_types=sorted(SUPPORTED_EXTENSIONS),
                type="filepath",
            )
            upload_button = gr.Button("Start analysis", variant="primary")
            overview = gr.Markdown("Upload a CSV, TSV, Excel, JSON, or Parquet file (up to 25 MB).")
            preview = gr.Dataframe(label="Data preview", interactive=False)

        with gr.Column(scale=2):
            chat = gr.Chatbot(label="Analysis", height=480)
            question = gr.Textbox(
                label="Question",
                placeholder="What appears to affect the target column?",
                lines=2,
            )
            ask_button = gr.Button("Ask", variant="primary")

    with gr.Accordion("Analysis details", open=False):
        analysis_state = gr.JSON(label="Analysis state")
        latest_tools = gr.JSON(label="Tools used for latest answer")

    upload_button.click(
        handle_upload,
        inputs=dataset_file,
        outputs=[session_id, overview, preview, chat, analysis_state, latest_tools],
    )
    for event in (ask_button.click, question.submit):
        event(
            handle_question,
            inputs=[question, session_id, chat],
            outputs=[question, chat, analysis_state, latest_tools],
        )

demo.queue(default_concurrency_limit=1)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
