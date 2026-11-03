"""Database configuration and session scope."""

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql+psycopg://coding:coding@127.0.0.1:5432/coding")


engine = create_engine(database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session() -> Generator[Session]:
    with SessionLocal() as session:
        yield session
