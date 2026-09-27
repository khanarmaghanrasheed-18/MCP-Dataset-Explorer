"""Shared dataset ingestion for the web and Gradio interfaces."""

import hashlib
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

from mcp_server import load_dataset
from state_store import StateStore


SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class UploadTooLargeError(ValueError):
    """Raised when an uploaded file exceeds the application limit."""


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


def ingest_dataset(
    source: BinaryIO,
    filename: str,
    store: StateStore,
    upload_dir: Path,
) -> tuple[dict[str, Any], Any]:
    """Copy, validate, and register a supported dataset from a file stream."""
    original_name = Path(filename or "dataset").name
    extension = Path(original_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type. Use one of: {allowed}.")

    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_path = upload_dir / f"{uuid4().hex}{extension}"
    total_bytes = 0
    digest = hashlib.sha256()

    try:
        with stored_path.open("wb") as destination:
            while chunk := source.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise UploadTooLargeError("Dataset exceeds the 25 MB upload limit.")
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
        return dataset, dataframe
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
