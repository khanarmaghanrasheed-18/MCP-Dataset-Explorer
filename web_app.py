import hashlib
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field

from agent_service import AgentService
from mcp_server import load_dataset
from state_store import StateStore


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / ".data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE_PATH = DATA_DIR / "dataset_explorer.db"
WEB_DIR = BASE_DIR / "web"
SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
store = StateStore(DATABASE_PATH)


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


def build_schema(dataframe: Any) -> dict[str, Any]:
    columns = []
    numerical_columns = []
    categorical_columns = []

    for column in dataframe.columns:
        series = dataframe[column]
        is_numerical = bool(series.dtype.kind in "biufc")
        column_type = "numerical" if is_numerical else "categorical"
        columns.append({
            "name": str(column), "dtype": str(series.dtype), "type": column_type,
            "missing": int(series.isna().sum()), "unique": int(series.nunique()),
        })

        if is_numerical:
            numerical_columns.append(str(column))
        else:
            categorical_columns.append(str(column))

    return {
        "rows": int(dataframe.shape[0]), "columns": int(dataframe.shape[1]),
        "column_details": columns, "numerical_columns": numerical_columns,
        "categorical_columns": categorical_columns,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    stack = AsyncExitStack()
    server_path = str(BASE_DIR / "mcp_server.py")
    parameters = StdioServerParameters(command=sys.executable, args=[server_path])

    try:
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
    original_name = Path(file.filename or "dataset").name
    extension = Path(original_name).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(400, f"Unsupported file type. Use one of: {allowed}.")

    stored_name = f"{uuid4().hex}{extension}"
    stored_path = UPLOAD_DIR / stored_name
    total_bytes = 0
    digest = hashlib.sha256()

    try:
        with stored_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Dataset exceeds the 25 MB upload limit.")
                digest.update(chunk)
                destination.write(chunk)

        dataframe = load_dataset(str(stored_path))
        schema = build_schema(dataframe)
        dataset = store.create_dataset(
            original_name,
            str(stored_path),
            extension,
            digest.hexdigest(),
            schema["rows"],
            schema["columns"],
            schema,
        )
    except HTTPException:
        stored_path.unlink(missing_ok=True)
        raise
    except Exception as error:
        stored_path.unlink(missing_ok=True)
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
