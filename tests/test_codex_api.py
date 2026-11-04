"""Codex account state gates real runs and remains scoped to a local user."""

import base64
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import main as api_module
from apps.api.db import get_session
from apps.api.models import Base, Project, Run, Task, User
from apps.api.service import token_digest
from coding_platform.codex_run import CODEX_TASKS
from coding_platform.contracts import ToolResult
from coding_platform.codex_roles import default_assignments


def test_codex_run_requires_account_and_creates_role_tasks(monkeypatch, tmp_path):
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

        def start(self):
            pass

        def call(self, method, params=None):
            assert method == "model/list"
            return {"data": [{"model": "gpt-6.1-sol"}, {"id": "gpt-6-astra"}]}

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
    monkeypatch.setattr(api_module, "data_root", lambda: tmp_path)
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
        invalid_reference = client.post(
            path,
            headers=headers,
            json={
                "prompt": "Make a timer",
                "references": [
                    {"name": "picture.png", "data_base64": base64.b64encode(b"image").decode()}
                ],
            },
        )
        assert invalid_reference.status_code == 422
        assert client.get("/api/codex/models", headers=headers).json() == {
            "models": ["gpt-6.1-sol", "gpt-6-astra"]
        }
        response = client.post(
            path, headers=headers, json={"prompt": "Make a timer", "engine": "codex"}
        )
        assert response.status_code == 202
        assert response.json()["engine"] == "codex"
        roles = client.get("/api/codex/roles", headers=headers)
        assert roles.status_code == 200
        assert roles.json()["assignments"]["researcher"]["provider"] == "codex"
        assert (
            client.put("/api/ai/keys/claude", headers=headers, json={"key": "x"}).status_code == 404
        )
        assignments = default_assignments()
        assignments["researcher"] = {"provider": "codex", "model": "gpt-6.1-sol"}
        assert (
            client.put(
                "/api/codex/roles", headers=headers, json={"assignments": assignments}
            ).status_code
            == 200
        )
        rejected = default_assignments()
        rejected["researcher"] = {"provider": "claude", "model": "test"}
        assert (
            client.put(
                "/api/codex/roles", headers=headers, json={"assignments": rejected}
            ).status_code
            == 422
        )
        assert client.get("/api/ai/roles", headers=headers).status_code == 404
        web_response = client.post(
            path, headers=headers, json={"prompt": "Make a browser game", "engine": "codex_web"}
        )
        assert web_response.status_code == 202
        assert web_response.json()["engine"] == "codex_web"
        assert web_response.json()["budget_usd"] is None
        reference_text = "The calculator must print the result in the terminal."
        auto_response = client.post(
            path,
            headers=headers,
            json={
                "prompt": "Make a calculator",
                "references": [
                    {
                        "name": "requirements.md",
                        "data_base64": base64.b64encode(reference_text.encode()).decode(),
                    }
                ],
            },
        )
        assert auto_response.status_code == 202
        assert auto_response.json()["engine"] == "codex_auto"
        auto_id = auto_response.json()["id"]
        attached = client.get(f"/api/runs/{auto_id}/references", headers=headers)
        assert attached.status_code == 200
        assert attached.json()[0]["name"] == "requirements.md"
        assert attached.json()[0]["text"] == reference_text
        assert client.get(f"/api/runs/{auto_id}/references").status_code == 401
        assert (tmp_path / "m3-runs" / auto_id / "references.json").is_file()
        snapshot = tmp_path / "m3-runs" / auto_id / "role-assignments.json"
        assert json.loads(snapshot.read_text())["researcher"] == assignments["researcher"]
        run_dir = tmp_path / "m3-runs" / auto_id
        (run_dir / "repo").mkdir(parents=True)
        (run_dir / "repo" / "app.py").write_text("print(input())", encoding="utf-8")
        (run_dir / "report.json").write_text(
            json.dumps({"target": "python_cli", "status": "COMPLETED", "tasks": []}),
            encoding="utf-8",
        )

        class FakeSandbox:
            def __init__(self, workspace, image):
                assert image == "ai-coding-m1:local"
                assert (workspace / "app.py").read_text(encoding="utf-8") == "print(input())"

            def execute(self, call):
                assert call.arguments["stdin"] == "hello\n"
                assert call.arguments["argv"] == ["python", "-I", "app.py"]
                return ToolResult(call.id, True, 0, stdout="hello\n")

        monkeypatch.setattr(api_module, "DockerSandbox", FakeSandbox)
        preview = client.post(
            f"/api/runs/{auto_id}/preview/terminal",
            headers=headers,
            json={"stdin": "hello\n"},
        )
        assert preview.status_code == 200
        assert preview.json()["stdout"] == "hello\n"
        assert (
            client.get(f"/api/runs/{auto_id}/report", headers=headers).json()["target"]
            == "python_cli"
        )
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
