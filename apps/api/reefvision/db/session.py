"""Database engine and session factory creation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    connect_args = (
        {"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {}
    )
    engine = create_engine(settings.resolved_database_url, connect_args=connect_args)
    if engine.dialect.name == "sqlite":
        # SQLite disables FK enforcement by default even when migrations
        # declare RESTRICT links. Every pooled desktop/API connection must
        # protect persisted review request and scientific parent records.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                enabled = cursor.execute("PRAGMA foreign_keys").fetchone()
                if enabled is None or enabled[0] != 1:
                    raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
            finally:
                cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
