"""Project deletion removes related records and files, while protecting active work."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import main as api_module
from apps.api.db import get_session
from apps.api.models import (
    AgentExecution,
    Approval,
    Artifact,
    Base,
    Event,
    Outbox,
    Project,
    Run,
    Task,
    ToolCallRecord,
    User,
)
from apps.api.service import token_digest


def test_delete_project_removes_history_and_rejects_active_runs(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        owner = User(name="delete-owner", token_hash=token_digest("owner-token"))
        other = User(name="delete-other", token_hash=token_digest("other-token"))
        session.add_all([owner, other])
        session.flush()
        project = Project(owner_id=owner.id, name="Old project")
        other_project = Project(owner_id=other.id, name="Keep")
        session.add_all([project, other_project])
        session.flush()
        run = Run(project_id=project.id, prompt="Old run", status="RUNNING")
        session.add(run)
        session.flush()
        task = Task(run_id=run.id, task_key="T1", title="Plan", agent_role="coordinator")
        session.add(task)
        session.flush()
        execution = AgentExecution(task_id=task.id)
        session.add(execution)
        session.flush()
        history = Event(run_id=run.id, seq=1, type="run.created")
        session.add(history)
        session.flush()
        session.add_all(
            [
                Outbox(event_id=history.id),
                ToolCallRecord(
                    execution_id=execution.id, idempotency_key="old-call", name="read_file"
                ),
                Approval(run_id=run.id, action="review"),
                Artifact(
                    run_id=run.id, path="source.zip", sha256="abc", size=3, storage_uri="local"
                ),
            ]
        )
        project_id, run_id, other_id = project.id, run.id, other_project.id

    for folder in ("m3-runs", "artifacts"):
        directory = tmp_path / folder / run_id
        directory.mkdir(parents=True)
        (directory / "sample.txt").write_text("data", encoding="utf-8")

    def test_session():
        with sessions() as session:
            yield session

    api_module.app.dependency_overrides[get_session] = test_session
    monkeypatch.setattr(api_module, "data_root", lambda: tmp_path)
    try:
        client = TestClient(api_module.app)
        path = f"/api/projects/{project_id}"
        assert (
            client.delete(path, headers={"Authorization": "Bearer other-token"}).status_code == 404
        )
        blocked = client.delete(path, headers={"Authorization": "Bearer owner-token"})
        assert blocked.status_code == 409
        assert (tmp_path / "m3-runs" / run_id).is_dir()
        with sessions.begin() as session:
            session.get(Run, run_id).status = "CANCELLED"
        deleted = client.delete(path, headers={"Authorization": "Bearer owner-token"})
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True, "removed_runs": 1, "cleanup_failed": False}
        assert client.get(path, headers={"Authorization": "Bearer owner-token"}).status_code == 404
        with sessions() as session:
            assert session.get(Project, other_id) is not None
            for model in (
                Run,
                Task,
                AgentExecution,
                ToolCallRecord,
                Event,
                Outbox,
                Artifact,
                Approval,
            ):
                assert session.scalars(select(model)).first() is None
        assert not (tmp_path / "m3-runs" / run_id).exists()
        assert not (tmp_path / "artifacts" / run_id).exists()
    finally:
        api_module.app.dependency_overrides.clear()
        engine.dispose()
