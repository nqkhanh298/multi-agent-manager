"""Kill a worker after a durable tool intent and verify conservative recovery.

Run with the normal worker stopped. This script creates its own disposable run.
"""

import multiprocessing
import os
import secrets
import signal
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.db import SessionLocal
from apps.api.main import app
from apps.api.models import AgentExecution, Event, Run, Task, ToolCallRecord, User
from apps.api.service import token_digest
from apps.worker import main as worker


def worker_with_fault_window() -> None:
    original = worker.record_tool_start

    def delay_after_intent(run_id, call):
        original(run_id, call)
        time.sleep(30)

    worker.record_tool_start = delay_after_intent
    worker.run_worker(once=True)


def main() -> None:
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as session:
        session.add(User(name=f"m6-fault-{uuid.uuid4().hex[:8]}", token_hash=token_digest(token)))
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post(
        "/api/projects", json={"name": "M6 fault injection"}, headers=headers
    ).json()
    run = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"prompt": "Build the fixed task manager benchmark"},
        headers=headers,
    ).json()
    run_id = run["id"]
    process = multiprocessing.Process(target=worker_with_fault_window)
    process.start()
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with SessionLocal() as session:
                started = session.scalar(
                    select(Event.id).where(Event.run_id == run_id, Event.type == "tool.started")
                )
            if started:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("worker did not record a tool intent")
        os.kill(process.pid, signal.SIGKILL)
        process.join(timeout=5)
        assert process.exitcode == -signal.SIGKILL
        assert worker.recover_stale_runs(stale_seconds=0) == [run_id]
        with SessionLocal() as session:
            assert session.get(Run, run_id).status == "BLOCKED"
            tool = session.scalar(
                select(ToolCallRecord).join(AgentExecution).join(Task).where(Task.run_id == run_id)
            )
            assert tool.status == "UNKNOWN"
        assert worker.process_run(run_id) == "SKIPPED"
        redis = worker.redis_client()
        try:
            redis.lrem(worker.QUEUE, 0, run_id)
            redis.lrem(worker.PROCESSING, 0, run_id)
        finally:
            redis.close()
        print(f"M6 worker-kill fault passed: run {run_id} BLOCKED, tool UNKNOWN, duplicate SKIPPED")
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


if __name__ == "__main__":
    main()
