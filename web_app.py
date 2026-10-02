import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field

from agent_service import AgentService
from dataset_upload import UploadTooLargeError, ingest_dataset
from state_store import StateStore
from remote_mcp import create_remote_mcp


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / ".data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE_PATH = DATA_DIR / "dataset_explorer.db"
WEB_DIR = BASE_DIR / "web"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
store = StateStore(DATABASE_PATH)
remote_mcp = create_remote_mcp(store, UPLOAD_DIR)
remote_http_app = remote_mcp.streamable_http_app()


class SessionRequest(BaseModel):
    dataset_id: str


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


def public_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": dataset["id"], "filename": dataset["filename"],
        "extension": dataset["extension"], "row_count": dataset["row_count"],
        "column_count": dataset["column_count"], "schema": dataset["schema"],
        "created_at": dataset["created_at"],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    stack = AsyncExitStack()
    server_path = str(BASE_DIR / "mcp_server.py")
    parameters = StdioServerParameters(command=sys.executable, args=[server_path])

    try:
        await stack.enter_async_context(remote_mcp.session_manager.run())
        read, write = await stack.enter_async_context(stdio_client(parameters))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        app.state.agent = AgentService(session, store)
        yield
    finally:
        await stack.aclose()


app = FastAPI(
    title="Dataset Explorer",
    description="Evidence-driven dataset analysis with Gemini and MCP tools.",
    version="3.0.0",
    lifespan=lifespan,
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/datasets")
async def upload_dataset(file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        dataset, _ = ingest_dataset(file.file, file.filename or "dataset", store, UPLOAD_DIR)
    except UploadTooLargeError as error:
        raise HTTPException(413, str(error)) from error
    except Exception as error:
        raise HTTPException(400, f"The dataset could not be read: {error}") from error
    finally:
        await file.close()

    return public_dataset(dataset)


@app.get("/api/datasets/{dataset_id}")
async def get_dataset(dataset_id: str) -> dict[str, Any]:
    dataset = store.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(404, "Dataset was not found.")
    return public_dataset(dataset)


@app.post("/api/sessions")
async def create_session(request: SessionRequest) -> dict[str, Any]:
    dataset = store.get_dataset(request.dataset_id)
    if dataset is None:
        raise HTTPException(404, "Dataset was not found.")

    session = store.create_session(dataset)
    return {
        "id": session["id"], "dataset": public_dataset(dataset),
        "state": session["state"],
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Analysis session was not found.")

    return {
        "id": session["id"], "dataset": public_dataset(session["dataset"]),
        "state": session["state"],
        "messages": store.recent_messages(session_id, limit=20),
    }


@app.post("/api/sessions/{session_id}/messages")
async def ask_question(
    session_id: str, payload: QuestionRequest, request: Request
) -> dict[str, Any]:
    try:
        return await request.app.state.agent.ask(session_id, payload.question.strip())
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        raise HTTPException(500, f"Analysis failed: {error}") from error


app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# The SDK owns the exact /mcp route. Mount last so existing web routes win and
# /mcp is served directly, without Starlette's /mcp -> /mcp/ mount redirect.
app.mount("/", remote_http_app)
