"""A cancel that races with pause must still leave no running task."""

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.models import Base, Project, Run, Task, User
from apps.worker import main as worker


def test_cancel_wins_if_worker_was_finishing_pause(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        user = User(name="control-user", token_hash="control-token")
        session.add(user)
        session.flush()
        project = Project(owner_id=user.id, name="Control")
        session.add(project)
        session.flush()
        run = Run(project_id=project.id, prompt="Build an app", engine="codex")
        session.add(run)
        session.flush()
        session.add(Task(run_id=run.id, task_key="T1", title="Plan", agent_role="coordinator"))
        run_id = run.id

    class FakeRunner:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, prompt, current_run_id):
            with sessions.begin() as session:
                session.get(Run, current_run_id).cancel_requested = True
                session.scalar(select(Task).where(Task.run_id == current_run_id)).status = "RUNNING"
            directory = tmp_path / "m3-runs" / current_run_id
            directory.mkdir(parents=True)
            (directory / "report.json").write_text(
                json.dumps({"status": "PAUSED"}), encoding="utf-8"
            )
            return {"status": "PAUSED"}

    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "data_root", lambda: tmp_path)
    monkeypatch.setattr(worker, "CodexRunRunner", FakeRunner)
    assert worker.process_run(run_id) == "CANCELLED"
    with sessions() as session:
        assert session.get(Run, run_id).status == "CANCELLED"
        assert session.scalar(select(Task).where(Task.run_id == run_id)).status == "CANCELLED"
    report = json.loads((tmp_path / "m3-runs" / run_id / "report.json").read_text())
    assert report["status"] == "CANCELLED"
    engine.dispose()
