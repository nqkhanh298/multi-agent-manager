"""Redis-backed worker that runs M3 and publishes durable events."""

import argparse
import hashlib
import json
import os

import redis
from sqlalchemy import select

from apps.api.db import SessionLocal
from apps.api.models import AgentExecution, Event, Outbox, Run, Task, ToolCallRecord, now_utc
from apps.api.service import (
    append_event,
    change_status,
    data_root,
    event_json,
    save_source_artifact,
)
from coding_platform.contracts import ToolCall, ToolResult
from coding_platform.m3 import M3Runner
from coding_platform.sandbox import DockerSandbox

QUEUE = "m4:queue"
PROCESSING = "m4:processing"


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))


def publish_outbox(client: redis.Redis, limit: int = 100) -> int:
    with SessionLocal.begin() as session:
        rows = session.scalars(
            select(Outbox).where(Outbox.published_at.is_(None)).limit(limit).with_for_update()
        ).all()
        for row in rows:
            event = session.get(Event, row.event_id)
            client.publish(f"m4:events:{event.run_id}", json.dumps(event_json(event)))
            row.published_at = now_utc()
        return len(rows)


def control_for(run_id: str) -> str | None:
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        if run.cancel_requested:
            return "CANCELLED"
        if run.pause_requested:
            return "PAUSED"
    return None


def record_m3_event(run_id: str, event_type: str, payload: dict) -> None:
    with SessionLocal.begin() as session:
        task = session.scalar(
            select(Task).where(Task.run_id == run_id, Task.task_key == payload["task_id"])
        )
        if task is not None:
            if event_type == "task.status":
                task.status = payload["status"]
            elif event_type == "task.merge" and payload["status"] == "MERGED":
                task.status = "COMPLETED"
            execution = session.scalar(
                select(AgentExecution).where(AgentExecution.task_id == task.id)
            )
            if execution is not None and event_type == "task.status":
                execution.status = payload["status"]
                if payload["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                    execution.ended_at = now_utc()
        append_event(session, run_id, event_type, payload)


def tool_key(run_id: str, call: ToolCall) -> str:
    return f"{run_id}:{call.id}"


def safe_arguments(call: ToolCall) -> dict:
    if call.name == "write_file":
        return {
            "path": call.arguments["path"],
            "content_sha256": hashlib.sha256(call.arguments["content"].encode()).hexdigest(),
        }
    if call.name == "run_command":
        return {
            "executable": call.arguments["argv"][0],
            "timeout_seconds": call.arguments["timeout_seconds"],
        }
    return {"path": call.arguments.get("path", ".")}


def record_tool_start(run_id: str, call: ToolCall) -> None:
    with SessionLocal.begin() as session:
        task_key = call.id.split("-", 1)[0]
        task = session.scalar(select(Task).where(Task.run_id == run_id, Task.task_key == task_key))
        if task is None:
            raise ValueError("tool call has no matching task")
        key = tool_key(run_id, call)
        if session.scalar(select(ToolCallRecord.id).where(ToolCallRecord.idempotency_key == key)):
            raise RuntimeError("tool call was already started; reconcile before replay")
        execution = session.scalar(select(AgentExecution).where(AgentExecution.task_id == task.id))
        if execution is None:
            execution = AgentExecution(task_id=task.id)
            session.add(execution)
            session.flush()
        session.add(
            ToolCallRecord(
                execution_id=execution.id,
                idempotency_key=key,
                name=call.name,
                arguments=safe_arguments(call),
            )
        )
        append_event(session, run_id, "tool.started", {"task_id": task_key, "tool": call.name})


def record_tool_finish(run_id: str, call: ToolCall, result: ToolResult | None) -> None:
    with SessionLocal.begin() as session:
        row = session.scalar(
            select(ToolCallRecord).where(ToolCallRecord.idempotency_key == tool_key(run_id, call))
        )
        row.status = "UNKNOWN" if result is None else ("COMPLETED" if result.ok else "FAILED")
        row.exit_code = None if result is None else result.exit_code
        append_event(
            session,
            run_id,
            "tool.unknown" if result is None else "tool.completed",
            {"task_id": call.id.split("-", 1)[0], "tool": call.name, "status": row.status},
        )


class AuditedSandbox:
    def __init__(self, base: DockerSandbox, run_id: str):
        self.base = base
        self.run_id = run_id

    def execute(self, call: ToolCall) -> ToolResult:
        record_tool_start(self.run_id, call)
        try:
            result = self.base.execute(call)
        except Exception:
            record_tool_finish(self.run_id, call, None)
            raise
        record_tool_finish(self.run_id, call, result)
        return result


def process_run(run_id: str) -> str:
    with SessionLocal.begin() as session:
        run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None or run.status != "CREATED":
            return "SKIPPED"
        if run.cancel_requested:
            change_status(session, run, "CANCELLED")
            return "CANCELLED"
        prompt = run.prompt
        change_status(session, run, "RUNNING")
    try:

        def sandbox_for(workspace, role):
            image = (
                "ai-coding-m3-frontend:local"
                if role in {"frontend_dev", "qa_frontend"}
                else "ai-coding-m1:local"
            )
            return AuditedSandbox(
                DockerSandbox(
                    workspace,
                    image=image,
                    cancel_check=lambda: control_for(run_id) == "CANCELLED",
                ),
                run_id,
            )

        report = M3Runner(
            data_root(),
            max_parallel=int(os.getenv("MAX_PARALLEL_TASKS", "2")),
            sandbox_factory=sandbox_for,
        ).run(
            prompt,
            run_id=run_id,
            control=lambda: control_for(run_id),
            on_event=lambda kind, payload: record_m3_event(run_id, kind, payload),
        )
        with SessionLocal.begin() as session:
            run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            run.report_ref = str(data_root() / "m3-runs" / run_id / "report.json")
            status = report["status"]
            if status == "COMPLETED":
                repo = data_root() / "m3-runs" / run_id / "repo"
                save_source_artifact(session, run_id, repo)
                append_event(session, run_id, "artifact.ready", {"path": "source.zip"})
            change_status(session, run, status, report.get("reason"))
        return status
    except Exception as exc:
        with SessionLocal.begin() as session:
            run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            change_status(session, run, "FAILED", type(exc).__name__)
        raise


def recover_processing(client: redis.Redis) -> None:
    """Redeliver unacknowledged jobs; state claim keeps duplicates harmless."""
    while client.rpoplpush(PROCESSING, QUEUE) is not None:
        pass


def run_worker(once: bool = False) -> None:
    client = redis_client()
    recover_processing(client)
    try:
        while True:
            publish_outbox(client)
            item = client.brpoplpush(QUEUE, PROCESSING, timeout=2)
            if item is None:
                if once:
                    return
                continue
            run_id = item.decode("utf-8")
            try:
                process_run(run_id)
            finally:
                client.lrem(PROCESSING, 1, item)
                publish_outbox(client)
            if once:
                return
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="process one queued job and exit")
    args = parser.parse_args()
    run_worker(once=args.once)


if __name__ == "__main__":
    main()
