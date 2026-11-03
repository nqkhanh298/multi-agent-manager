"""Owner-scoped source browser and report filtering for M5."""

import json
import subprocess

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import main as api_module
from apps.api.db import get_session
from apps.api.models import Base, Project, Run, User
from apps.api.service import token_digest


def test_source_and_report_require_owner_and_hide_secrets(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    local_sessions = sessionmaker(engine, expire_on_commit=False)
    with local_sessions.begin() as session:
        owner = User(name="m5-owner", token_hash=token_digest("owner-token"))
        other = User(name="m5-other", token_hash=token_digest("other-token"))
        session.add_all([owner, other])
        session.flush()
        project = Project(name="Demo", description="", owner_id=owner.id)
        session.add(project)
        session.flush()
        run = Run(project_id=project.id, prompt="Build app")
        session.add(run)
        session.flush()
        run_id = run.id

    def test_session():
        with local_sessions() as session:
            yield session

    api_module.app.dependency_overrides[get_session] = test_session
    monkeypatch.setattr(api_module, "data_root", lambda: tmp_path)
    repo = tmp_path / "m3-runs" / run_id / "repo"
    repo.mkdir(parents=True)
    (repo / "App.jsx").write_text("export default function Old() {}", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "App.jsx"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "start",
        ],
        check=True,
    )
    (repo / "App.jsx").write_text("export default function App() {}", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "App.jsx"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "change",
        ],
        check=True,
    )
    (repo / ".env").write_text("SECRET=hidden", encoding="utf-8")
    (repo / "private.key").write_text("private", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET=outside", encoding="utf-8")
    try:
        (repo / "leak.py").symlink_to(outside)
    except OSError:
        pass  # Creating symlinks may require elevated permissions on Windows.
    (repo.parent / "report.json").write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "parallel_overlap_ms": 15,
                "tasks": [
                    {
                        "task_id": "T1",
                        "status": "COMPLETED",
                        "workspace": "/secret/path",
                        "test_stdout": "ok",
                    }
                ],
                "merges": [],
                "integration": {"stdout": "4 passed", "exit_code": 0},
            }
        ),
        encoding="utf-8",
    )
    try:
        client = TestClient(api_module.app)
        owner_headers = {"Authorization": "Bearer owner-token"}
        other_headers = {"Authorization": "Bearer other-token"}
        files = client.get(f"/api/runs/{run_id}/files", headers=owner_headers)
        assert [item["path"] for item in files.json()] == ["App.jsx"]
        assert (
            client.get(f"/api/runs/{run_id}/files/App.jsx", headers=owner_headers)
            .json()["content"]
            .startswith("export")
        )
        assert (
            client.get(f"/api/runs/{run_id}/files/.env", headers=owner_headers).status_code == 404
        )
        assert (
            client.get(f"/api/runs/{run_id}/files/leak.py", headers=owner_headers).status_code
            == 404
        )
        assert client.get(f"/api/runs/{run_id}/files", headers=other_headers).status_code == 404
        diff = client.get(f"/api/runs/{run_id}/diff?path=App.jsx", headers=owner_headers).json()
        assert "+export default function App() {}" in diff["diff"]
        assert (
            client.get(f"/api/runs/{run_id}/diff?path=.env", headers=owner_headers).status_code
            == 404
        )
        assert (
            client.get(f"/api/runs/{run_id}/diff?path=App.jsx", headers=other_headers).status_code
            == 404
        )
        report = client.get(f"/api/runs/{run_id}/report", headers=owner_headers).json()
        assert report["integration"]["stdout"] == "4 passed"
        assert "/secret/path" not in json.dumps(report)
    finally:
        api_module.app.dependency_overrides.clear()
        engine.dispose()
