"""Persistent control-plane records."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_project_status", "project_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(20), default="demo")
    status: Mapped[str] = mapped_column(String(32), default="CREATED")
    version: Mapped[int] = mapped_column(Integer, default=0)
    pause_requested: Mapped[bool] = mapped_column(default=False)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    report_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_usd: Mapped[float] = mapped_column(Float, default=5.0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    max_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_run_status", "run_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    task_key: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    agent_role: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    workspace_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="STARTED")
    model: Mapped[str] = mapped_column(String(100), default="mock")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class ToolCallRecord(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(ForeignKey("agent_executions.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(40))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="STARTED")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq"),
        Index("ix_events_run_seq", "run_id", "seq"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    path: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    storage_uri: Mapped[str] = mapped_column(Text)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    action: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
