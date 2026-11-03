"""Durable tool-call intent/results for local M2 recovery."""

import json
import sqlite3
from pathlib import Path

from .contracts import ToolCall, ToolResult


class UncertainToolCall(RuntimeError):
    pass


class ToolJournal:
    def __init__(self, database_path: Path, sandbox):
        self.database_path = database_path
        self.sandbox = sandbox
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS tool_calls ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, args_json TEXT NOT NULL, "
                "status TEXT NOT NULL, result_json TEXT)"
            )

    def _connect(self):
        return sqlite3.connect(self.database_path, timeout=10)

    def execute(self, call: ToolCall) -> ToolResult:
        args_json = json.dumps(call.arguments, sort_keys=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT name, args_json, status, result_json FROM tool_calls WHERE id = ?",
                (call.id,),
            ).fetchone()
            if row:
                if row[0] != call.name or row[1] != args_json:
                    raise UncertainToolCall("tool call ID reused with different arguments")
                if row[2] != "completed":
                    raise UncertainToolCall(
                        "tool call outcome unknown; manual reconciliation required"
                    )
                return ToolResult.from_dict(json.loads(row[3]))
            db.execute(
                "INSERT INTO tool_calls (id, name, args_json, status) VALUES (?, ?, ?, 'started')",
                (call.id, call.name, args_json),
            )
        # If the process dies after this point, resume blocks rather than repeating a side effect.
        result = self.sandbox.execute(call)
        with self._connect() as db:
            db.execute(
                "UPDATE tool_calls SET status = 'completed', result_json = ? WHERE id = ?",
                (json.dumps(result.__dict__), call.id),
            )
        return result
