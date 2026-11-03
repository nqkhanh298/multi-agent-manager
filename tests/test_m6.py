"""Budget enforcement and failure recovery invariants."""

import io
import urllib.error
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.budget import (
    BudgetExceeded,
    BudgetLimits,
    charge_model_usage,
    enforce_tool_budget,
    run_budget_reason,
)
from apps.api import main as api_module
from apps.api.models import (
    Approval,
    AgentExecution,
    Base,
    Event,
    Project,
    Run,
    Task,
    ToolCallRecord,
    User,
)
from apps.worker import main as worker
from coding_platform.contracts import ToolCall
from coding_platform.m2_openai import OpenAIJSONClient
from coding_platform.openai_provider import OpenAIResponsesProvider


def test_budget_limits_and_model_usage(monkeypatch):
    monkeypatch.setenv("MAX_RUN_USD", "2")
    monkeypatch.setenv("MAX_RUN_SECONDS", "60")
    monkeypatch.setenv("MAX_AGENT_STEPS", "3")
    assert BudgetLimits.from_env() == BudgetLimits(2.0, 60, 3)
    run = SimpleNamespace(
        created_at=datetime.now(timezone.utc), max_seconds=60, spent_usd=0.0, budget_usd=2.0
    )
    execution = SimpleNamespace(input_tokens=0, output_tokens=0, cost_usd=0.0)
    assert charge_model_usage(None, run, execution, 1_000_000, 500_000, 1.0, 2.0) is False
    assert run.spent_usd == 2.0
    assert execution.input_tokens == 1_000_000
    assert run_budget_reason(run) == "run USD budget exceeded"
    run.spent_usd = 0.0
    run.created_at -= timedelta(seconds=61)
    assert run_budget_reason(run) == "run time budget exceeded"
    monkeypatch.setenv("MAX_RUN_USD", "-1")
    with pytest.raises(ValueError):
        BudgetLimits.from_env()


def test_stale_worker_blocks_uncertain_tool_and_duplicate_claim(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    with sessions.begin() as session:
        user = User(name="m6", token_hash="test")
        session.add(user)
        session.flush()
        project = Project(owner_id=user.id, name="Demo")
        session.add(project)
        session.flush()
        old = Run(
            project_id=project.id,
            prompt="old",
            status="RUNNING",
            heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        )
        fresh = Run(
            project_id=project.id,
            prompt="fresh",
            status="RUNNING",
            heartbeat_at=datetime.now(timezone.utc),
        )
        session.add_all([old, fresh])
        session.flush()
        task = Task(run_id=old.id, task_key="T1", title="build", agent_role="backend_dev")
        session.add(task)
        session.flush()
        execution = AgentExecution(task_id=task.id)
        session.add(execution)
        session.flush()
        session.add(
            ToolCallRecord(execution_id=execution.id, idempotency_key="once", name="write_file")
        )
        old_id, fresh_id = old.id, fresh.id

    assert worker.recover_stale_runs(30) == [old_id]
    assert worker.process_run(old_id) == "SKIPPED"
    with sessions() as session:
        assert session.get(Run, old_id).status == "BLOCKED"
        assert session.get(Run, old_id).cancel_requested is True
        assert session.get(Run, fresh_id).status == "RUNNING"
        assert session.scalar(select(ToolCallRecord.status)) == "UNKNOWN"
        assert session.scalar(select(Event.type).where(Event.run_id == old_id)) == "run.status"
    engine.dispose()


def test_tool_step_budget_stops_before_side_effect():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        user = User(name="steps", token_hash="steps")
        session.add(user)
        session.flush()
        project = Project(owner_id=user.id, name="Demo")
        session.add(project)
        session.flush()
        run = Run(project_id=project.id, prompt="test")
        session.add(run)
        session.flush()
        task = Task(run_id=run.id, task_key="T1", title="build", agent_role="backend_dev")
        session.add(task)
        session.flush()
        execution = AgentExecution(task_id=task.id)
        session.add(execution)
        session.flush()
        session.add(
            ToolCallRecord(execution_id=execution.id, idempotency_key="one", name="write_file")
        )
        session.flush()
        with pytest.raises(BudgetExceeded, match="tool-call"):
            enforce_tool_budget(session, run, task, 1)
    engine.dispose()


def test_sandbox_failure_marks_tool_outcome_unknown(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    with sessions.begin() as session:
        user = User(name="crash", token_hash="crash")
        session.add(user)
        session.flush()
        project = Project(owner_id=user.id, name="Demo")
        session.add(project)
        session.flush()
        run = Run(project_id=project.id, prompt="test")
        session.add(run)
        session.flush()
        session.add(Task(run_id=run.id, task_key="T1", title="build", agent_role="backend_dev"))
        run_id = run.id

    class CrashedSandbox:
        def execute(self, _call):
            raise RuntimeError("sandbox lost")

    call = ToolCall("T1-write", "write_file", {"path": "demo.py", "content": "safe"})
    with pytest.raises(RuntimeError, match="sandbox lost"):
        worker.AuditedSandbox(CrashedSandbox(), run_id).execute(call)
    with sessions() as session:
        assert session.scalar(select(ToolCallRecord.status)) == "UNKNOWN"
        assert session.scalars(select(Event.type).order_by(Event.seq)).all() == [
            "tool.started",
            "tool.unknown",
        ]
    engine.dispose()


@pytest.mark.parametrize("failure", ["timeout", "rate_limit"])
def test_model_errors_are_bounded_and_sanitized(monkeypatch, failure):
    def fail_request(_request, timeout):
        assert timeout == 90
        if failure == "timeout":
            raise TimeoutError("private-key-should-not-appear")
        raise urllib.error.HTTPError(
            "https://api.openai.com/v1/responses", 429, "rate", {}, io.BytesIO()
        )

    monkeypatch.setattr("coding_platform.openai_provider.urllib.request.urlopen", fail_request)
    monkeypatch.setattr("coding_platform.m2_openai.urllib.request.urlopen", fail_request)
    expected = "timed out" if failure == "timeout" else "rate limit"
    with pytest.raises(RuntimeError, match=expected) as first:
        OpenAIResponsesProvider("test-model", api_key="private-key").next("build", [])
    with pytest.raises(RuntimeError, match=expected) as second:
        OpenAIJSONClient("test-model", api_key="private-key").complete(
            "test", {"type": "object", "properties": {}}, "test", "build"
        )
    assert "private-key" not in str(first.value) + str(second.value)


def test_budget_approval_increases_cap_and_report_path_is_private():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        user = User(name="approval", token_hash="approval")
        session.add(user)
        session.flush()
        project = Project(owner_id=user.id, name="Demo")
        session.add(project)
        session.flush()
        run = Run(
            project_id=project.id, prompt="test", budget_usd=5, report_ref="/private/report.json"
        )
        session.add(run)
        session.flush()
        approval = Approval(run_id=run.id, action="increase_budget", payload={"usd": 1})
        session.add(approval)
        session.commit()
        assert api_module.run_payload(run)["report_ref"] == f"/api/runs/{run.id}/report"
        result = api_module.decide_approval(
            approval.id,
            api_module.ApprovalDecision(decision="approve"),
            session,
            user,
        )
        assert result["status"] == "APPROVED"
        assert session.get(Run, run.id).budget_usd == 6
        assert session.scalars(select(Event.type).order_by(Event.seq)).all() == [
            "run.budget_increased",
            "approval.decided",
        ]
    engine.dispose()
