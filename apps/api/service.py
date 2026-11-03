"""Transactional state changes, event journal, and artifact packaging."""

import hashlib
import io
import os
import zipfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Artifact, Event, Outbox, Project, Run, User, new_id, now_utc

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "BLOCKED"}


def data_root() -> Path:
    return Path(os.getenv("M4_DATA_ROOT", ".local/platform")).resolve()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate(session: Session, token: str) -> User | None:
    if not token or len(token) > 256:
        return None
    return session.scalar(select(User).where(User.token_hash == token_digest(token)))


def owned_project(session: Session, project_id: str, user: User) -> Project | None:
    return session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == user.id)
    )


def owned_run(session: Session, run_id: str, user: User) -> Run | None:
    return session.scalar(
        select(Run).join(Project).where(Run.id == run_id, Project.owner_id == user.id)
    )


def append_event(session: Session, run_id: str, event_type: str, payload: dict) -> Event:
    # Locking the run serializes sequence assignment across API and worker processes.
    session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    seq = session.scalar(
        select(func.coalesce(func.max(Event.seq), 0)).where(Event.run_id == run_id)
    )
    event = Event(id=new_id(), run_id=run_id, seq=seq + 1, type=event_type, payload=payload)
    session.add(event)
    session.add(Outbox(event_id=event.id))
    return event


def change_status(session: Session, run: Run, status: str, reason: str | None = None) -> None:
    if run.status == status:
        return
    old = run.status
    run.status = status
    run.version += 1
    run.updated_at = now_utc()
    append_event(
        session,
        run.id,
        "run.status",
        {"from": old, "to": status, **({"reason": reason[:300]} if reason else {})},
    )


def event_json(event: Event) -> dict:
    return {
        "event_id": event.id,
        "run_id": event.run_id,
        "sequence": event.seq,
        "type": event.type,
        "payload": event.payload,
        "timestamp": event.created_at.isoformat(),
    }


def safe_source_zip(repo: Path) -> bytes:
    """Package source without Git internals, generated dependencies or secrets."""
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(repo.rglob("*")):
            relative = path.relative_to(repo)
            if any(
                part in {".git", "node_modules", "dist", "__pycache__"} for part in relative.parts
            ):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            if path.name.startswith(".env") or path.suffix in {".pem", ".key"}:
                continue
            size = path.stat().st_size
            total += size
            if total > 20_000_000:
                raise ValueError("source artifact exceeds 20 MB")
            archive.write(path, relative.as_posix())
    return buffer.getvalue()


def save_source_artifact(session: Session, run_id: str, repo: Path) -> Artifact:
    content = safe_source_zip(repo)
    directory = data_root() / "artifacts" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "source.zip"
    target.write_bytes(content)
    artifact = Artifact(
        run_id=run_id,
        path="source.zip",
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
        storage_uri=str(target),
    )
    session.add(artifact)
    return artifact
