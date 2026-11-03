"""Control-plane invariants that do not need running infrastructure."""

import io
import zipfile

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.models import Base, Event, Outbox, Project, Run, User
from apps.api.service import append_event, authenticate, owned_run, safe_source_zip, token_digest


def test_owner_scope_and_transactional_event_sequence():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = User(name="owner", token_hash=token_digest("owner-token"))
        stranger = User(name="stranger", token_hash=token_digest("stranger-token"))
        session.add_all([owner, stranger])
        session.flush()
        project = Project(owner_id=owner.id, name="A", description="")
        session.add(project)
        session.flush()
        run = Run(project_id=project.id, prompt="Build app")
        session.add(run)
        session.flush()
        append_event(session, run.id, "run.created", {})
        session.flush()
        append_event(session, run.id, "run.status", {"to": "RUNNING"})
        session.commit()
        assert authenticate(session, "owner-token").id == owner.id
        assert authenticate(session, "wrong") is None
        assert owned_run(session, run.id, owner) is not None
        assert owned_run(session, run.id, stranger) is None
        assert session.scalars(select(Event.seq).order_by(Event.seq)).all() == [1, 2]
        assert session.query(Outbox).count() == 2
    engine.dispose()


def test_source_zip_excludes_secrets_and_generated_directories(tmp_path):
    (tmp_path / "backend.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=yes", encoding="utf-8")
    (tmp_path / "private.key").write_text("secret", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("code", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("repo", encoding="utf-8")
    with zipfile.ZipFile(io.BytesIO(safe_source_zip(tmp_path))) as archive:
        assert archive.namelist() == ["backend.py"]
