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
        # declare RESTRICT links. Check both newly opened and reused pooled
        # connections: a local PRAGMA can disable enforcement after connect.
        def _enforce_foreign_keys(dbapi_connection: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                enabled = cursor.execute("PRAGMA foreign_keys").fetchone()
                if enabled is None or enabled[0] != 1:
                    cursor.execute("PRAGMA foreign_keys=ON")
                    enabled = cursor.execute("PRAGMA foreign_keys").fetchone()
                    if enabled is None or enabled[0] != 1:
                        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
            finally:
                cursor.close()

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            _enforce_foreign_keys(dbapi_connection)

        @event.listens_for(engine, "checkout")
        def _verify_pooled_foreign_keys(
            dbapi_connection: Any, _connection_record: Any, _connection_proxy: Any
        ) -> None:
            _enforce_foreign_keys(dbapi_connection)

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
