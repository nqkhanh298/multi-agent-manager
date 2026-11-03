"""Authenticated HTTP and WebSocket control plane for M4."""

import asyncio
import hashlib
import os
from pathlib import Path

import redis
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from coding_platform.m3 import MockM3Coordinator

from .db import SessionLocal, get_session
from .models import (
    AgentExecution,
    Approval,
    Artifact,
    Event,
    Project,
    Run,
    Task,
    ToolCallRecord,
    User,
)
from .service import (
    append_event,
    authenticate,
    change_status,
    data_root,
    event_json,
    owned_project,
    owned_run,
)

app = FastAPI(title="AI Coding Platform API", version="0.4.0")
bearer = HTTPBearer(auto_error=False)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=4000)


class RunCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


def queue_run(run_id: str) -> None:
    client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    try:
        client.lpush("m4:queue", run_id)
    except redis.RedisError as exc:
        raise HTTPException(503, "worker queue unavailable") from exc
    finally:
        client.close()


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    user = authenticate(session, credentials.credentials) if credentials else None
    if user is None:
        raise HTTPException(401, "valid bearer token required")
    return user


def project_payload(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "created_at": project.created_at,
    }


def run_payload(run: Run) -> dict:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "version": run.version,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "report_ref": run.report_ref,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/projects", status_code=201)
def create_project(
    body: ProjectCreate, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    project = Project(owner_id=user.id, name=body.name.strip(), description=body.description)
    if not project.name:
        raise HTTPException(422, "name must not be blank")
    session.add(project)
    session.commit()
    return project_payload(project)


@app.get("/api/projects")
def list_projects(
    session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list:
    projects = session.scalars(select(Project).where(Project.owner_id == user.id)).all()
    return [project_payload(project) for project in projects]


@app.get("/api/projects/{project_id}")
def get_project(
    project_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    project = owned_project(session, project_id, user)
    if project is None:
        raise HTTPException(404, "project not found")
    return project_payload(project)


@app.post("/api/projects/{project_id}/runs", status_code=202)
def create_run(
    project_id: str,
    body: RunCreate,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    if owned_project(session, project_id, user) is None:
        raise HTTPException(404, "project not found")
    plan = MockM3Coordinator().create_plan(body.prompt)
    run = Run(project_id=project_id, prompt=body.prompt)
    session.add(run)
    session.flush()
    for spec in plan.tasks:
        session.add(
            Task(
                run_id=run.id,
                task_key=spec.id,
                title=spec.title,
                agent_role=spec.agent,
                dependencies=spec.depends_on,
                acceptance_criteria=spec.acceptance_criteria,
            )
        )
    append_event(session, run.id, "run.created", {"project_id": project_id})
    session.commit()
    queue_run(run.id)
    return run_payload(run)


@app.get("/api/projects/{project_id}/runs")
def list_project_runs(
    project_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list:
    if owned_project(session, project_id, user) is None:
        raise HTTPException(404, "project not found")
    runs = session.scalars(
        select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
    ).all()
    return [run_payload(run) for run in runs]


@app.get("/api/runs/{run_id}")
def get_run(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    run = owned_run(session, run_id, user)
    if run is None:
        raise HTTPException(404, "run not found")
    return run_payload(run)


@app.get("/api/runs/{run_id}/tasks")
def list_tasks(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    tasks = session.scalars(select(Task).where(Task.run_id == run_id).order_by(Task.task_key)).all()
    return [
        {
            "id": task.task_key,
            "title": task.title,
            "agent_role": task.agent_role,
            "status": task.status,
            "depends_on": task.dependencies,
            "workspace_ref": task.workspace_ref,
        }
        for task in tasks
    ]


@app.get("/api/runs/{run_id}/events")
def list_events(
    run_id: str,
    after_seq: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list:
    if after_seq < 0:
        raise HTTPException(422, "after_seq must be nonnegative")
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    events = session.scalars(
        select(Event)
        .where(Event.run_id == run_id, Event.seq > after_seq)
        .order_by(Event.seq)
        .limit(500)
    ).all()
    return [event_json(event) for event in events]


@app.get("/api/runs/{run_id}/tool-calls")
def list_tool_calls(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    rows = session.execute(
        select(ToolCallRecord, Task.task_key)
        .join(AgentExecution, ToolCallRecord.execution_id == AgentExecution.id)
        .join(Task, AgentExecution.task_id == Task.id)
        .where(Task.run_id == run_id)
    ).all()
    return [
        {
            "task_id": task_key,
            "idempotency_key": call.idempotency_key,
            "name": call.name,
            "arguments": call.arguments,
            "status": call.status,
            "exit_code": call.exit_code,
        }
        for call, task_key in rows
    ]


@app.post("/api/runs/{run_id}/pause")
def pause_run(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    run = owned_run(session, run_id, user)
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status == "CREATED":
        change_status(session, run, "PAUSED")
    elif run.status == "RUNNING" and not run.pause_requested:
        run.pause_requested = True
        append_event(session, run.id, "run.pause_requested", {})
    elif run.status != "PAUSED":
        raise HTTPException(409, "run cannot be paused")
    session.commit()
    return run_payload(run)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    run = owned_run(session, run_id, user)
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status in {"CREATED", "PAUSED"}:
        run.cancel_requested = True
        change_status(session, run, "CANCELLED")
    elif run.status == "RUNNING" and not run.cancel_requested:
        run.cancel_requested = True
        append_event(session, run.id, "run.cancel_requested", {})
    elif run.status not in {"CANCELLED"}:
        raise HTTPException(409, "run cannot be cancelled")
    session.commit()
    return run_payload(run)


@app.post("/api/runs/{run_id}/resume")
def resume_run(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    run = owned_run(session, run_id, user)
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status != "PAUSED":
        raise HTTPException(409, "only paused runs can resume")
    run.pause_requested = False
    change_status(session, run, "CREATED")
    session.commit()
    queue_run(run.id)
    return run_payload(run)


@app.post("/api/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    approval = session.get(Approval, approval_id)
    if approval is None or owned_run(session, approval.run_id, user) is None:
        raise HTTPException(404, "approval not found")
    if approval.status != "PENDING":
        raise HTTPException(409, "approval already decided")
    from .models import now_utc

    approval.status = "APPROVED" if body.decision == "approve" else "REJECTED"
    approval.decided_at = now_utc()
    append_event(session, approval.run_id, "approval.decided", {"decision": body.decision})
    session.commit()
    return {"id": approval.id, "status": approval.status}


@app.get("/api/runs/{run_id}/approvals")
def list_approvals(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    rows = session.scalars(select(Approval).where(Approval.run_id == run_id)).all()
    return [
        {"id": item.id, "action": item.action, "payload": item.payload, "status": item.status}
        for item in rows
    ]


@app.get("/api/runs/{run_id}/artifacts")
def list_artifacts(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    artifacts = session.scalars(select(Artifact).where(Artifact.run_id == run_id)).all()
    return [
        {"id": item.id, "path": item.path, "sha256": item.sha256, "size": item.size}
        for item in artifacts
    ]


@app.get("/api/runs/{run_id}/download")
def download_source(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> FileResponse:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    artifact = session.scalar(
        select(Artifact).where(Artifact.run_id == run_id, Artifact.path == "source.zip")
    )
    if artifact is None:
        raise HTTPException(404, "source artifact not ready")
    target = Path(artifact.storage_uri).resolve()
    base = (data_root() / "artifacts" / run_id).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404, "source artifact unavailable")
    if hashlib.sha256(target.read_bytes()).hexdigest() != artifact.sha256:
        raise HTTPException(409, "source artifact checksum mismatch")
    return FileResponse(target, media_type="application/zip", filename=f"{run_id}-source.zip")


@app.websocket("/ws/runs/{run_id}")
async def run_events(websocket: WebSocket, run_id: str, after_seq: int = 0) -> None:
    await websocket.accept()
    scheme, _, token = (websocket.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer":
        try:
            message = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            token = message.get("token", "")
        except (TimeoutError, ValueError, WebSocketDisconnect):
            await websocket.close(code=4401)
            return
    with SessionLocal() as session:
        user = authenticate(session, token)
        if user is None or owned_run(session, run_id, user) is None:
            await websocket.close(code=4403)
            return
    seq = max(after_seq, 0)
    try:
        while True:
            with SessionLocal() as session:
                rows = session.scalars(
                    select(Event)
                    .where(Event.run_id == run_id, Event.seq > seq)
                    .order_by(Event.seq)
                    .limit(100)
                ).all()
                payloads = [event_json(item) for item in rows]
            for payload in payloads:
                await websocket.send_json(payload)
                seq = payload["sequence"]
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.25)
            except TimeoutError:
                pass
    except WebSocketDisconnect:
        return
