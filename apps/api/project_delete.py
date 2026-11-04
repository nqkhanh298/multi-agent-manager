"""Delete a finished project's database records and local run files."""

import shutil
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    AgentExecution,
    Approval,
    Artifact,
    Event,
    Outbox,
    Project,
    Run,
    Task,
    ToolCallRecord,
)
from .service import TERMINAL


class ProjectHasActiveRuns(ValueError):
    pass


def delete_project_records(session: Session, project: Project) -> list[str]:
    runs = session.scalars(select(Run).where(Run.project_id == project.id).with_for_update()).all()
    if any(run.status not in TERMINAL for run in runs):
        raise ProjectHasActiveRuns("Hãy hủy hoặc hoàn tất các lượt chạy trước khi xóa dự án")
    run_ids = [run.id for run in runs]
    run_query = select(Run.id).where(Run.project_id == project.id)
    task_query = select(Task.id).where(Task.run_id.in_(run_query))
    execution_query = select(AgentExecution.id).where(AgentExecution.task_id.in_(task_query))
    event_query = select(Event.id).where(Event.run_id.in_(run_query))

    session.execute(delete(Outbox).where(Outbox.event_id.in_(event_query)))
    session.execute(delete(Event).where(Event.run_id.in_(run_query)))
    session.execute(delete(ToolCallRecord).where(ToolCallRecord.execution_id.in_(execution_query)))
    session.execute(delete(AgentExecution).where(AgentExecution.task_id.in_(task_query)))
    session.execute(delete(Approval).where(Approval.run_id.in_(run_query)))
    session.execute(delete(Artifact).where(Artifact.run_id.in_(run_query)))
    session.execute(delete(Task).where(Task.run_id.in_(run_query)))
    session.execute(delete(Run).where(Run.project_id == project.id))
    session.delete(project)
    return run_ids


def delete_project_files(root: Path, run_ids: list[str]) -> list[str]:
    failed: list[str] = []
    for run_id in run_ids:
        try:
            UUID(run_id)
        except ValueError:
            failed.append(run_id)
            continue
        for folder in ("m3-runs", "artifacts"):
            parent = (root / folder).resolve()
            target = parent / run_id
            if target.is_symlink() or target.resolve().parent != parent:
                failed.append(run_id)
                continue
            try:
                if target.is_dir():
                    shutil.rmtree(target)
            except OSError:
                failed.append(run_id)
    return sorted(set(failed))
