"""Small SQLite repository with atomic saves and read-only history queries."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from ..agent.protocol import AgentRun
from ..schemas import Schema

APPLICATION_ID = 0x56415350
SCHEMA_VERSION = 1


class StorageSchemaError(RuntimeError):
    pass


class StorageRecordError(RuntimeError):
    pass


class StoragePathError(RuntimeError):
    pass


class RunSummary(Schema):
    id: int = Field(ge=1)
    saved_at: str
    backend: Literal["mock", "deepseek"]
    question: str
    directory: str
    status: Literal["completed", "max_steps", "backend_error"]
    decision_steps: int = Field(ge=1)
    tool_calls: int = Field(ge=0)


class StoredRun(Schema):
    summary: RunSummary
    run: AgentRun


SUMMARY_COLUMNS = "id, saved_at, backend, question, directory, status, decision_steps, tool_calls"


class RunRepository:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()
        if self.path.suffix.lower() not in {".sqlite3", ".sqlite", ".db"}:
            raise StoragePathError("History path must end in .sqlite3, .sqlite or .db")

    @staticmethod
    def _check_schema(connection: sqlite3.Connection, initialize: bool = False) -> None:
        app_id = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if app_id == APPLICATION_ID and version == SCHEMA_VERSION:
            return
        objects = connection.execute("SELECT name FROM sqlite_master").fetchall()
        if not initialize or app_id != 0 or version != 0 or objects:
            raise StorageSchemaError("Database is not a supported VASP-Copilot history database")
        connection.execute("""
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY,
                saved_at TEXT NOT NULL,
                backend TEXT NOT NULL CHECK (backend IN ('mock', 'deepseek')),
                question TEXT NOT NULL,
                directory TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('completed', 'max_steps', 'backend_error')),
                decision_steps INTEGER NOT NULL CHECK (decision_steps >= 1),
                tool_calls INTEGER NOT NULL CHECK (tool_calls >= 0),
                run_json TEXT NOT NULL
            )
        """)
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def save(self, run: AgentRun, backend: str) -> RunSummary:
        # Only the run snapshot and backend label are stored, never backend config.
        summary = RunSummary(id=1, saved_at=datetime.now(timezone.utc).isoformat(), backend=backend,
                             question=run.state.question, directory=run.state.directory,
                             status=run.status, decision_steps=run.decision_steps, tool_calls=len(run.state.history))
        serialized = run.model_dump_json()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            with connection:
                # Lock before initializing so concurrent first saves cannot race on schema creation.
                connection.execute("BEGIN IMMEDIATE")
                self._check_schema(connection, initialize=True)
                cursor = connection.execute(
                    "INSERT INTO runs (saved_at, backend, question, directory, status, decision_steps, tool_calls, run_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (summary.saved_at, backend, summary.question, summary.directory, summary.status,
                     summary.decision_steps, summary.tool_calls, serialized),
                )
                summary.id = cursor.lastrowid
        return summary

    def _open_readonly(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError("History database does not exist")
        # URI encoding handles spaces, # and ? in paths; mode=ro never creates a database.
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            self._check_schema(connection)
        except Exception:
            connection.close()
            raise
        return connection

    @staticmethod
    def _summary(row: sqlite3.Row) -> RunSummary:
        try:
            return RunSummary.model_validate({column: row[column] for column in SUMMARY_COLUMNS.split(", ")})
        except (ValidationError, KeyError, IndexError):
            raise StorageRecordError("Stored summary is invalid") from None

    def list_runs(self, limit: int = 10) -> list[RunSummary]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("History limit must be an integer in 1-100")
        with closing(self._open_readonly()) as connection:
            rows = connection.execute(f"SELECT {SUMMARY_COLUMNS} FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, run_id: int) -> StoredRun | None:
        if type(run_id) is not int or run_id < 1:
            raise ValueError("Run ID must be a positive integer")
        with closing(self._open_readonly()) as connection:
            row = connection.execute(f"SELECT {SUMMARY_COLUMNS}, run_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        summary = self._summary(row)
        try:
            run = AgentRun.model_validate_json(row["run_json"])
        except (ValidationError, TypeError, ValueError):
            raise StorageRecordError("Stored run is invalid") from None
        if (summary.question != run.state.question or summary.directory != run.state.directory or
                summary.status != run.status or summary.decision_steps != run.decision_steps or
                summary.tool_calls != len(run.state.history)):
            raise StorageRecordError("Stored summary differs from run snapshot")
        return StoredRun(summary=summary, run=run)
