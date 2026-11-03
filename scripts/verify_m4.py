"""Exercise the M4 API, database, queue, worker, event replay and artifact flow."""

import io
import secrets
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.db import SessionLocal
from apps.api.main import app
from apps.api.models import Approval, Event, Outbox, User
from apps.api.service import token_digest
from apps.worker import main as worker
from apps.worker.main import run_worker
from coding_platform.contracts import ToolCall
from coding_platform.sandbox import DockerSandbox, SandboxCancelled


def user() -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as session:
        session.add(User(name=f"verify-{uuid.uuid4().hex[:12]}", token_hash=token_digest(token)))
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    owner = user()
    stranger = user()
    client = TestClient(app)
    assert client.post("/api/projects", json={"name": "M4 benchmark"}).status_code == 401
    project = client.post("/api/projects", json={"name": "M4 benchmark"}, headers=owner).json()
    assert client.get(f"/api/projects/{project['id']}", headers=stranger).status_code == 404

    created = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"prompt": "Build a task management app"},
        headers=owner,
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    assert [
        task["status"] for task in client.get(f"/api/runs/{run_id}/tasks", headers=owner).json()
    ] == ["PENDING"] * 3
    run_worker(once=True)

    run = client.get(f"/api/runs/{run_id}", headers=owner).json()
    assert run["status"] == "COMPLETED", run
    tasks = client.get(f"/api/runs/{run_id}/tasks", headers=owner).json()
    assert [task["status"] for task in tasks] == ["COMPLETED"] * 3, tasks
    events = client.get(f"/api/runs/{run_id}/events", headers=owner).json()
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert (
        client.get(
            f"/api/runs/{run_id}/events?after_seq={events[-2]['sequence']}", headers=owner
        ).json()[0]["sequence"]
        == events[-1]["sequence"]
    )
    calls = client.get(f"/api/runs/{run_id}/tool-calls", headers=owner).json()
    assert len(calls) >= 9 and all(call["status"] == "COMPLETED" for call in calls)
    assert all("content" not in call["arguments"] for call in calls)
    assert client.get(f"/api/runs/{run_id}/tool-calls", headers=stranger).status_code == 404
    with client.websocket_connect(f"/ws/runs/{run_id}?after_seq=0", headers=owner) as ws:
        assert ws.receive_json()["sequence"] == 1
    assert client.get(f"/api/runs/{run_id}", headers=stranger).status_code == 404
    assert (
        client.get(f"/api/projects/{project['id']}/runs", headers=owner).json()[0]["id"] == run_id
    )

    with SessionLocal.begin() as session:
        approval = Approval(run_id=run_id, action="increase_budget", payload={"usd": 1})
        session.add(approval)
        session.flush()
        approval_id = approval.id
    assert client.get(f"/api/runs/{run_id}/approvals", headers=owner).json()[0]["id"] == approval_id
    assert (
        client.post(
            f"/api/approvals/{approval_id}/decision",
            json={"decision": "approve"},
            headers=stranger,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=owner
        ).json()["status"]
        == "APPROVED"
    )

    manifest = client.get(f"/api/runs/{run_id}/artifacts", headers=owner).json()
    assert [item["path"] for item in manifest] == ["source.zip"]
    download = client.get(f"/api/runs/{run_id}/download", headers=owner)
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
        assert "backend.py" in names and "App.jsx" in names
        assert not any(name.startswith(".git/") or name.startswith(".env") for name in names)
    assert client.get(f"/api/runs/{run_id}/download", headers=stranger).status_code == 404

    paused = client.post(
        f"/api/projects/{project['id']}/runs", json={"prompt": "Another app"}, headers=owner
    ).json()["id"]
    assert client.post(f"/api/runs/{paused}/pause", headers=owner).json()["status"] == "PAUSED"
    run_worker(once=True)
    assert client.get(f"/api/runs/{paused}", headers=owner).json()["status"] == "PAUSED"
    assert client.post(f"/api/runs/{paused}/resume", headers=owner).json()["status"] == "CREATED"
    run_worker(once=True)
    assert client.get(f"/api/runs/{paused}", headers=owner).json()["status"] == "COMPLETED"

    midrun = client.post(
        f"/api/projects/{project['id']}/runs", json={"prompt": "Pause during work"}, headers=owner
    ).json()["id"]
    original_record = worker.record_m3_event

    def request_pause_after_merge(run_id: str, kind: str, payload: dict) -> None:
        original_record(run_id, kind, payload)
        if run_id == midrun and kind == "task.merge" and payload["task_id"] == "T1":
            with SessionLocal.begin() as session:
                session.get(worker.Run, run_id).pause_requested = True

    worker.record_m3_event = request_pause_after_merge
    try:
        run_worker(once=True)
    finally:
        worker.record_m3_event = original_record
    assert client.get(f"/api/runs/{midrun}", headers=owner).json()["status"] == "PAUSED"
    assert client.post(f"/api/runs/{midrun}/resume", headers=owner).json()["status"] == "CREATED"
    run_worker(once=True)
    assert client.get(f"/api/runs/{midrun}", headers=owner).json()["status"] == "COMPLETED"

    cancelled = client.post(
        f"/api/projects/{project['id']}/runs", json={"prompt": "Cancel me"}, headers=owner
    ).json()["id"]
    assert (
        client.post(f"/api/runs/{cancelled}/cancel", headers=owner).json()["status"] == "CANCELLED"
    )
    run_worker(once=True)
    assert client.get(f"/api/runs/{cancelled}", headers=owner).json()["status"] == "CANCELLED"
    active = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"prompt": "Cancel while running"},
        headers=owner,
    ).json()["id"]
    worker_thread = threading.Thread(target=run_worker, kwargs={"once": True})
    worker_thread.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        observed = client.get(f"/api/runs/{active}/events", headers=owner).json()
        if any(item["type"] == "tool.started" for item in observed):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("active run did not start a tool")
    client.post(f"/api/runs/{active}/cancel", headers=owner)
    worker_thread.join(timeout=20)
    assert not worker_thread.is_alive(), "worker did not stop after cancellation"
    assert client.get(f"/api/runs/{active}", headers=owner).json()["status"] == "CANCELLED"
    with tempfile.TemporaryDirectory() as directory:
        stop = threading.Event()
        timer = threading.Timer(1.0, stop.set)
        timer.start()
        try:
            sandbox = DockerSandbox(Path(directory), cancel_check=stop.is_set)
            try:
                sandbox.execute(
                    ToolCall(
                        "cancel-live-command",
                        "run_command",
                        {
                            "argv": ["python", "-c", "import time; time.sleep(10)"],
                            "timeout_seconds": 20,
                        },
                    )
                )
            except SandboxCancelled:
                pass
            else:
                raise AssertionError("running sandbox command did not cancel")
        finally:
            timer.cancel()
    with SessionLocal() as session:
        assert session.scalar(select(Event).where(Event.run_id == run_id)) is not None
        assert not session.scalars(select(Outbox).where(Outbox.published_at.is_(None))).first()
    print(
        f"M4 verified: run {run_id}, {len(events)} ordered events, source ZIP, "
        "auth, pause/resume, and live sandbox cancellation"
    )


if __name__ == "__main__":
    main()
