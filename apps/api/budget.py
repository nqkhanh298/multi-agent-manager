"""Limits for a run and accounting hooks for model-backed agents."""

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AgentExecution, Run, Task, ToolCallRecord


class BudgetExceeded(RuntimeError):
    pass


def positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not 0 < value < float("inf"):
        raise ValueError(f"{name} must be a finite positive number")
    return value


@dataclass(frozen=True)
class BudgetLimits:
    usd: float
    seconds: int
    tool_calls_per_task: int

    @classmethod
    def from_env(cls) -> "BudgetLimits":
        return cls(
            usd=positive_float("MAX_RUN_USD", 5.0),
            seconds=positive_int("MAX_RUN_SECONDS", 1800),
            tool_calls_per_task=positive_int("MAX_AGENT_STEPS", 20),
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def run_budget_reason(run: Run, now: datetime | None = None) -> str | None:
    current = now or datetime.now(timezone.utc)
    if (current - _aware(run.created_at)).total_seconds() > run.max_seconds:
        return "run time budget exceeded"
    if run.spent_usd >= run.budget_usd:
        return "run USD budget exceeded"
    return None


def enforce_tool_budget(session: Session, run: Run, task: Task, limit: int) -> None:
    reason = run_budget_reason(run)
    if reason:
        raise BudgetExceeded(reason)
    count = session.scalar(
        select(func.count(ToolCallRecord.id))
        .join(AgentExecution, ToolCallRecord.execution_id == AgentExecution.id)
        .where(AgentExecution.task_id == task.id)
    )
    if count >= limit:
        raise BudgetExceeded("task tool-call budget exceeded")


def charge_model_usage(
    session: Session,
    run: Run,
    execution: AgentExecution,
    input_tokens: int,
    output_tokens: int,
    input_usd_per_million: float,
    output_usd_per_million: float,
) -> bool:
    """Record actual usage; return False when the resulting spend reaches the cap."""
    if min(input_tokens, output_tokens, input_usd_per_million, output_usd_per_million) < 0:
        raise ValueError("usage and prices must be nonnegative")
    cost = (
        input_tokens * input_usd_per_million + output_tokens * output_usd_per_million
    ) / 1_000_000
    execution.input_tokens += input_tokens
    execution.output_tokens += output_tokens
    execution.cost_usd += cost
    run.spent_usd += cost
    return run_budget_reason(run) is None
