import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class StateStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    column_count INTEGER NOT NULL,
                    schema_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_cache (
                    cache_key TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id);

                CREATE INDEX IF NOT EXISTS idx_evidence_session
                ON evidence(session_id, created_at);
                """
            )

    def create_dataset(
        self,
        filename: str,
        stored_path: str,
        extension: str,
        file_hash: str,
        row_count: int,
        column_count: int,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        dataset_id = uuid4().hex
        created_at = utc_now()

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    id, filename, stored_path, extension, file_hash,
                    row_count, column_count, schema_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id, filename, stored_path, extension, file_hash,
                    row_count, column_count, json_text(schema), created_at,
                ),
            )

        return self.get_dataset(dataset_id)

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM datasets WHERE id = ?", (dataset_id,)
            ).fetchone()

        if row is None:
            return None

        dataset = dict(row)
        dataset["schema"] = json.loads(dataset.pop("schema_json"))
        return dataset

    def create_session(self, dataset: dict[str, Any]) -> dict[str, Any]:
        session_id = uuid4().hex
        created_at = utc_now()
        state = {
            "goal": None,
            "target": None,
            "plan": [],
            "findings": [],
            "hypotheses": [],
            "completed_actions": [],
            "next_action": None,
            "status": "new",
            "dataset_summary": dataset["schema"],
        }

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, dataset_id, state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, dataset["id"], json_text(state), created_at, created_at),
            )

        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()

        if row is None:
            return None

        session = dict(row)
        session["state"] = json.loads(session.pop("state_json"))
        session["dataset"] = self.get_dataset(session["dataset_id"])
        return session

    def save_state(self, session_id: str, state: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sessions SET state_json = ?, updated_at = ? WHERE id = ?",
                (json_text(state), utc_now(), session_id),
            )

    def add_message(self, session_id: str, role: str, content: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (session_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, utc_now()),
            )

    def recent_messages(self, session_id: str, limit: int = 4) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at FROM messages
                WHERE session_id = ? ORDER BY id DESC LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        messages = []
        for row in reversed(rows):
            messages.append(dict(row))
        return messages

    def save_evidence(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        evidence_id = f"evidence_{uuid4().hex[:12]}"

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO evidence (
                    id, session_id, tool_name, arguments_json, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id, session_id, tool_name, json_text(arguments),
                    json_text(result), utc_now(),
                ),
            )

        return evidence_id

    def cache_key(
        self, dataset_hash: str, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        payload = f"{dataset_hash}:{tool_name}:{json_text(arguments)}:v1"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_cached_result(self, cache_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM tool_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()

        if row is None:
            return None
        return json.loads(row["result_json"])

    def save_cached_result(
        self,
        cache_key: str,
        dataset_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO tool_cache (
                    cache_key, dataset_id, tool_name, arguments_json, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key, dataset_id, tool_name, json_text(arguments),
                    json_text(result), utc_now(),
                ),
            )
