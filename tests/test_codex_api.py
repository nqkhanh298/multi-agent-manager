"""Codex account state gates real runs and remains scoped to a local user."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import main as api_module
from apps.api.db import get_session
from apps.api.models import Base, Project, Run, Task, User
from apps.api.service import token_digest
from coding_platform.codex_run import CODEX_TASKS


def test_codex_run_requires_account_and_creates_role_tasks(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        owner = User(name="codex-owner", token_hash=token_digest("codex-owner-token"))
        session.add(owner)
        session.flush()
        project = Project(owner_id=owner.id, name="Local app")
        session.add(project)
        session.flush()
        project_id = project.id

    def get_test_session():
        with sessions() as session:
            yield session

    class FakeCodex:
        connected = False

        def account(self):
            return {
                "account": {"type": "chatgpt", "email": "user@example.com"}
                if self.connected
                else None
            }

    fake = FakeCodex()
    api_module.app.dependency_overrides[get_session] = get_test_session
    monkeypatch.setattr(api_module, "codex_client", lambda user: fake)
    monkeypatch.setattr(api_module, "queue_run", lambda run_id: None)
    try:
        client = TestClient(api_module.app)
        headers = {"Authorization": "Bearer codex-owner-token"}
        path = f"/api/projects/{project_id}/runs"
        assert client.get("/api/codex/account", headers=headers).json()["connected"] is False
        assert (
            client.post(
                path, headers=headers, json={"prompt": "Make a timer", "engine": "codex"}
            ).status_code
            == 409
        )
        fake.connected = True
        response = client.post(
            path, headers=headers, json={"prompt": "Make a timer", "engine": "codex"}
        )
        assert response.status_code == 202
        assert response.json()["engine"] == "codex"
        run_id = response.json()["id"]
        with sessions.begin() as session:
            session.get(Run, run_id).status = "RUNNING"
        paused = client.post(f"/api/runs/{run_id}/pause", headers=headers)
        assert paused.json()["control_request"] == "pause"
        cancelled = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert cancelled.json()["control_request"] == "cancel"
        with sessions() as session:
            tasks = session.query(Task).filter(Task.run_id == run_id).order_by(Task.task_key).all()
            assert [task.agent_role for task in tasks] == [task.agent for task in CODEX_TASKS]
    finally:
        api_module.app.dependency_overrides.clear()
        engine.dispose()
