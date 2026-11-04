"""Authenticated HTTP and WebSocket control plane for M4."""

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import redis
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from coding_platform.m3 import MockM3Coordinator
from coding_platform.codex_app_server import CodexAppServer, CodexUnavailable
from coding_platform.codex_run import CODEX_TASKS
from coding_platform.contracts import ToolCall
from coding_platform.sandbox import DockerSandbox, SandboxUnavailable

from .budget import BudgetLimits
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
from .project_delete import ProjectHasActiveRuns, delete_project_files, delete_project_records
from .service import (
    append_event,
    authenticate,
    change_status,
    data_root,
    event_json,
    owned_project,
    owned_run,
)

app = FastAPI(title="AI Coding Platform API", version="0.6.0")
bearer = HTTPBearer(auto_error=False)
_codex_clients: dict[str, CodexAppServer] = {}
_codex_clients_lock = threading.Lock()


def codex_client(user: User) -> CodexAppServer:
    with _codex_clients_lock:
        if user.id not in _codex_clients:
            _codex_clients[user.id] = CodexAppServer(data_root() / "codex-accounts" / user.id)
        return _codex_clients[user.id]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=4000)


class RunCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    engine: str = Field(default="codex_auto", pattern="^(demo|codex|codex_web|codex_auto)$")


class CodexLoginRequest(BaseModel):
    method: str = Field(default="browser", pattern="^(browser|device)$")


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


class TerminalPreviewInput(BaseModel):
    stdin: str = Field(default="", max_length=4096)


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
        "prompt": run.prompt,
        "engine": run.engine,
        "status": run.status,
        "control_request": (
            "cancel"
            if run.status == "RUNNING" and run.cancel_requested
            else "pause"
            if run.status == "RUNNING" and run.pause_requested
            else None
        ),
        "version": run.version,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "report_ref": f"/api/runs/{run.id}/report" if run.report_ref else None,
        "budget_usd": None if run.engine.startswith("codex") else run.budget_usd,
        "spent_usd": None if run.engine.startswith("codex") else run.spent_usd,
        "max_seconds": run.max_seconds,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/codex/account")
def codex_account(user: User = Depends(current_user)) -> dict:
    try:
        account = codex_client(user).account().get("account")
    except CodexUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "connected": bool(account and account.get("type") == "chatgpt"),
        "email": account.get("email") if account and account.get("type") == "chatgpt" else None,
        "plan_type": account.get("planType")
        if account and account.get("type") == "chatgpt"
        else None,
    }


@app.post("/api/codex/login")
def codex_login(body: CodexLoginRequest, user: User = Depends(current_user)) -> dict:
    try:
        login = codex_client(user).begin_login(body.method)
    except CodexUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "login_id": login.get("loginId"),
        "auth_url": login.get("authUrl"),
        "verification_url": login.get("verificationUrl"),
        "user_code": login.get("userCode"),
    }


@app.post("/api/codex/logout")
def codex_logout(user: User = Depends(current_user)) -> dict:
    try:
        codex_client(user).logout()
    except CodexUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"connected": False}


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


@app.delete("/api/projects/{project_id}")
def delete_project(
    project_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    project = session.scalar(
        select(Project)
        .where(Project.id == project_id, Project.owner_id == user.id)
        .with_for_update()
    )
    if project is None:
        raise HTTPException(404, "project not found")
    try:
        run_ids = delete_project_records(session, project)
    except ProjectHasActiveRuns as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    failed = delete_project_files(data_root(), run_ids)
    return {"deleted": True, "removed_runs": len(run_ids), "cleanup_failed": bool(failed)}


@app.post("/api/projects/{project_id}/runs", status_code=202)
def create_run(
    project_id: str,
    body: RunCreate,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    if (
        session.scalar(
            select(Project)
            .where(Project.id == project_id, Project.owner_id == user.id)
            .with_for_update()
        )
        is None
    ):
        raise HTTPException(404, "project not found")
    if body.engine.startswith("codex"):
        try:
            account = codex_client(user).account().get("account")
        except CodexUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        if not account or account.get("type") != "chatgpt":
            raise HTTPException(409, "connect your ChatGPT account to Codex first")
        plan = CODEX_TASKS
    else:
        plan = MockM3Coordinator().create_plan(body.prompt).tasks
    limits = BudgetLimits.from_env()
    run = Run(
        project_id=project_id,
        prompt=body.prompt,
        engine=body.engine,
        budget_usd=limits.usd,
        spent_usd=0.0,
        max_seconds=limits.seconds,
    )
    session.add(run)
    session.flush()
    for spec in plan:
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
    executions = {
        execution.task_id: execution
        for execution in session.scalars(
            select(AgentExecution).where(AgentExecution.task_id.in_([task.id for task in tasks]))
        )
    }

    def duration_ms(execution: AgentExecution | None) -> int | None:
        if execution is None:
            return None
        started = execution.started_at
        ended = execution.ended_at or datetime.now(timezone.utc)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)
        return max(0, int((ended - started).total_seconds() * 1000))

    return [
        {
            "id": task.task_key,
            "title": task.title,
            "agent_role": task.agent_role,
            "model": executions[task.id].model if task.id in executions else None,
            "status": task.status,
            "depends_on": task.dependencies,
            "workspace_ref": None,
            "duration_ms": duration_ms(executions.get(task.id)),
            "input_tokens": executions[task.id].input_tokens if task.id in executions else 0,
            "output_tokens": executions[task.id].output_tokens if task.id in executions else 0,
            "cost_usd": executions[task.id].cost_usd if task.id in executions else 0.0,
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


def source_repo(run_id: str) -> Path:
    return (data_root() / "m3-runs" / run_id / "repo").resolve()


def visible_file(path: Path, repo: Path) -> bool:
    relative = path.relative_to(repo)
    return not (
        path.is_symlink()
        or any(part in {".git", "node_modules", "dist", "__pycache__"} for part in relative.parts)
        or path.name.startswith(".env")
        or path.suffix in {".key", ".pem", ".pyc"}
    )


@app.get("/api/runs/{run_id}/files")
def list_source_files(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> list:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    repo = source_repo(run_id)
    if not repo.is_dir():
        return []
    files = []
    for path in sorted(repo.rglob("*")):
        if path.is_file() and visible_file(path, repo) and path.stat().st_size <= 1_000_000:
            files.append({"path": path.relative_to(repo).as_posix(), "size": path.stat().st_size})
        if len(files) >= 300:
            break
    return files


@app.get("/api/runs/{run_id}/files/{file_path:path}")
def read_source_file(
    run_id: str,
    file_path: str,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    repo = source_repo(run_id)
    target = (repo / file_path).resolve()
    if (
        not target.is_relative_to(repo)
        or not target.is_file()
        or not visible_file(target, repo)
        or target.stat().st_size > 1_000_000
    ):
        raise HTTPException(404, "file not found")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(415, "file is not UTF-8 text") from exc
    return {"path": target.relative_to(repo).as_posix(), "content": content}


@app.get("/api/runs/{run_id}/diff")
def get_source_diff(
    run_id: str,
    path: str,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    repo = source_repo(run_id)
    target = (repo / path).resolve()
    if (
        not target.is_relative_to(repo)
        or not target.is_file()
        or not visible_file(target, repo)
        or target.stat().st_size > 1_000_000
    ):
        raise HTTPException(404, "file not found")
    relative = target.relative_to(repo).as_posix()
    try:
        roots = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if roots.returncode != 0 or not roots.stdout.strip():
            return {"path": relative, "diff": ""}
        first_commit = roots.stdout.splitlines()[0]
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "diff",
                "--no-ext-diff",
                "--no-color",
                first_commit,
                "HEAD",
                "--",
                relative,
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"path": relative, "diff": ""}
    return {"path": relative, "diff": result.stdout[:100_000] if result.returncode == 0 else ""}


@app.get("/api/runs/{run_id}/report")
def get_report(
    run_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)
) -> dict:
    if owned_run(session, run_id, user) is None:
        raise HTTPException(404, "run not found")
    report_path = data_root() / "m3-runs" / run_id / "report.json"
    if not report_path.is_file():
        raise HTTPException(404, "report not ready")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "target": report.get("target"),
        "status": report["status"],
        "parallel_overlap_ms": report.get("parallel_overlap_ms", 0),
        "tasks": [
            {
                "task_id": item["task_id"],
                "status": item["status"],
                "test_stdout": item.get("test_stdout", "")[:8000],
                "reason": item.get("reason", "")[:1000],
            }
            for item in report.get("tasks", [])
        ],
        "merges": report.get("merges", []),
        "integration": {
            key: value[:8000] if isinstance(value, str) else value
            for key, value in (report.get("integration") or {}).items()
        },
    }


@app.post("/api/runs/{run_id}/preview/terminal")
def preview_terminal(
    run_id: str,
    body: TerminalPreviewInput,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    run = owned_run(session, run_id, user)
    if run is None:
        raise HTTPException(404, "run not found")
    report_path = data_root() / "m3-runs" / run_id / "report.json"
    if run.engine not in {"codex", "codex_auto"} or not report_path.is_file():
        raise HTTPException(409, "terminal preview is unavailable for this run")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    repo = source_repo(run_id)
    source = repo / "app.py"
    if (
        report.get("target", "python_cli") != "python_cli"
        or not source.is_file()
        or source.is_symlink()
        or not source.resolve().is_relative_to(repo)
    ):
        raise HTTPException(409, "terminal source is not ready")
    if source.stat().st_size > 100_000:
        raise HTTPException(413, "terminal source is too large")
    try:
        with tempfile.TemporaryDirectory(prefix="coding-preview-") as directory:
            (Path(directory) / "app.py").write_bytes(source.read_bytes())
            result = DockerSandbox(Path(directory), image="ai-coding-m1:local").execute(
                ToolCall(
                    str(uuid.uuid4()),
                    "run_command",
                    {
                        "argv": ["python", "-I", "app.py"],
                        "timeout_seconds": 10,
                        "stdin": body.stdin,
                    },
                )
            )
    except SandboxUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
    }


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
        report_path = data_root() / "m3-runs" / run.id / "report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["status"] = "CANCELLED"
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        for task in session.scalars(
            select(Task).where(Task.run_id == run.id, Task.status == "RUNNING")
        ):
            task.status = "CANCELLED"
            append_event(
                session, run.id, "task.status", {"task_id": task.task_key, "status": "CANCELLED"}
            )
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

    if body.decision == "approve" and approval.action == "increase_budget":
        amount = approval.payload.get("usd")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not 0 < amount <= 100
        ):
            raise HTTPException(422, "invalid budget increase")
        run = session.get(Run, approval.run_id)
        run.budget_usd += float(amount)
        append_event(session, run.id, "run.budget_increased", {"usd": amount})
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
