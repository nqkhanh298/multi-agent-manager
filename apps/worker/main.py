"""Redis-backed worker that runs M3 and publishes durable events."""

import argparse
import hashlib
import json
import os
import threading
from datetime import timezone

import redis
from sqlalchemy import select

from apps.api.budget import (
    BudgetExceeded,
    BudgetLimits,
    enforce_tool_budget,
    positive_int,
    run_budget_reason,
)
from apps.api.db import SessionLocal
from apps.api.models import (
    AgentExecution,
    Event,
    Outbox,
    Project,
    Run,
    Task,
    ToolCallRecord,
    now_utc,
)
from apps.api.service import (
    append_event,
    change_status,
    data_root,
    event_json,
    save_source_artifact,
)
from coding_platform.contracts import ToolCall, ToolResult
from coding_platform.m3 import M3Runner
from coding_platform.codex_run import CodexRunRunner
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
        if run_budget_reason(run):
            return "CANCELLED"
        if run.pause_requested:
            return "PAUSED"
    return None


def record_m3_event(run_id: str, event_type: str, payload: dict) -> None:
    with SessionLocal.begin() as session:
        task_id = payload.get("task_id")
        task = (
            session.scalar(select(Task).where(Task.run_id == run_id, Task.task_key == task_id))
            if task_id is not None
            else None
        )
        if task is not None:
            if event_type == "task.status":
                task.status = payload["status"]
            elif event_type == "task.merge" and payload["status"] == "MERGED":
                task.status = "COMPLETED"
            execution = session.scalar(
                select(AgentExecution).where(AgentExecution.task_id == task.id)
            )
            run_engine = session.scalar(select(Run.engine).where(Run.id == run_id))
            if (
                execution is None
                and run_engine.startswith("codex")
                and event_type == "task.status"
                and payload["status"] == "RUNNING"
            ):
                execution = AgentExecution(task_id=task.id, model="Codex")
                session.add(execution)
            if execution is not None and event_type == "task.status":
                execution.status = payload["status"]
                if payload["status"] == "RUNNING":
                    execution.started_at = now_utc()
                    execution.ended_at = None
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
        run = session.get(Run, run_id)
        enforce_tool_budget(session, run, task, BudgetLimits.from_env().tool_calls_per_task)
        if task.status == "PENDING":
            task.status = "RUNNING"
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
        reason = run_budget_reason(run)
        if reason:
            change_status(session, run, "BLOCKED", reason)
            return "BLOCKED"
        prompt = run.prompt
        engine = run.engine
        owner_id = session.scalar(select(Project.owner_id).where(Project.id == run.project_id))
        run.heartbeat_at = now_utc()
        change_status(session, run, "RUNNING")
    stop_heartbeat = threading.Event()
    heartbeat = threading.Thread(target=heartbeat_loop, args=(run_id, stop_heartbeat), daemon=True)
    heartbeat.start()
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

        if engine.startswith("codex"):
            report = CodexRunRunner(
                data_root(),
                event=lambda kind, payload: record_m3_event(run_id, kind, payload),
                control=lambda: control_for(run_id),
                codex_home=data_root() / "codex-accounts" / owner_id,
                target="auto"
                if engine == "codex_auto"
                else "web"
                if engine == "codex_web"
                else "python_cli",
            ).run(prompt, run_id)
        else:
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
            if run.status != "RUNNING":
                return run.status
            run.report_ref = str(data_root() / "m3-runs" / run_id / "report.json")
            status = report["status"]
            if run.cancel_requested:
                status = "CANCELLED"
                report["status"] = status
                (data_root() / "m3-runs" / run_id / "report.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
                for task in session.scalars(
                    select(Task).where(Task.run_id == run_id, Task.status == "RUNNING")
                ):
                    task.status = "CANCELLED"
                    append_event(
                        session,
                        run_id,
                        "task.status",
                        {"task_id": task.task_key, "status": "CANCELLED"},
                    )
            reason = run_budget_reason(run)
            if reason and not run.cancel_requested:
                status = "BLOCKED"
                report["reason"] = reason
                report["status"] = status
                (data_root() / "m3-runs" / run_id / "report.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
            if status == "COMPLETED":
                repo = data_root() / "m3-runs" / run_id / "repo"
                save_source_artifact(session, run_id, repo)
                append_event(session, run_id, "artifact.ready", {"path": "source.zip"})
            change_status(session, run, status, report.get("reason"))
        return status
    except BudgetExceeded as exc:
        with SessionLocal.begin() as session:
            run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            change_status(session, run, "BLOCKED", str(exc))
        return "BLOCKED"
    except Exception as exc:
        with SessionLocal.begin() as session:
            run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run.status == "RUNNING":
                change_status(session, run, "FAILED", type(exc).__name__)
        raise
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=2)


def heartbeat_loop(run_id: str, stop: threading.Event) -> None:
    while not stop.wait(5):
        try:
            with SessionLocal.begin() as session:
                run = session.get(Run, run_id)
                if run is None or run.status != "RUNNING":
                    return
                run.heartbeat_at = now_utc()
        except Exception:
            return


def recover_stale_runs(stale_seconds: int = 30) -> list[str]:
    """Block abandoned runs; never replay uncertain tool side effects."""
    recovered = []
    now = now_utc()
    with SessionLocal.begin() as session:
        runs = session.scalars(
            select(Run).where(Run.status == "RUNNING").limit(100).with_for_update(skip_locked=True)
        ).all()
        for run in runs:
            last = run.heartbeat_at or run.updated_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < stale_seconds:
                continue
            tasks = session.scalars(select(Task.id).where(Task.run_id == run.id)).all()
            for call in session.scalars(
                select(ToolCallRecord)
                .join(AgentExecution)
                .where(AgentExecution.task_id.in_(tasks), ToolCallRecord.status == "STARTED")
            ):
                call.status = "UNKNOWN"
            run.cancel_requested = True
            change_status(
                session, run, "BLOCKED", "worker heartbeat expired; reconcile tool side effects"
            )
            recovered.append(run.id)
    return recovered


def recover_created_runs(client: redis.Redis) -> int:
    """Requeue runs whose API-to-Redis handoff may have failed."""
    with SessionLocal() as session:
        ids = session.scalars(select(Run.id).where(Run.status == "CREATED").limit(100)).all()
    for run_id in ids:
        client.lpush(QUEUE, run_id)
    return len(ids)


def recover_processing(client: redis.Redis) -> None:
    """Redeliver unacknowledged jobs; state claim keeps duplicates harmless."""
    while client.rpoplpush(PROCESSING, QUEUE) is not None:
        pass


def run_worker(once: bool = False) -> None:
    client = redis_client()
    recover_stale_runs(positive_int("WORKER_STALE_SECONDS", 30))
    recover_processing(client)
    if client.llen(QUEUE) == 0:
        recover_created_runs(client)
    try:
        while True:
            publish_outbox(client)
            item = client.brpoplpush(QUEUE, PROCESSING, timeout=2)
            if item is None:
                if once:
                    return
                recover_stale_runs(positive_int("WORKER_STALE_SECONDS", 30))
                recover_created_runs(client)
                continue
            run_id = item.decode("utf-8")
            try:
                process_run(run_id)
            except Exception as exc:
                print(f"worker run {run_id} failed: {type(exc).__name__}")
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
