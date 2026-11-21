"""FastAPI dependencies."""

import errno
import sqlite3
from collections.abc import Generator

from fastapi import Request
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from reefvision.domain.errors import StorageCapacityError


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield a session from the current application instance."""

    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        try:
            yield session
        except DBAPIError as exc:
            code = getattr(exc.orig, "sqlite_errorcode", None)
            if (
                isinstance(exc.orig, sqlite3.Error)
                and isinstance(code, int)
                and code & 0xFF == sqlite3.SQLITE_FULL
            ):
                raise StorageCapacityError() from exc
            raise
        except OSError as exc:
            if exc.errno in (errno.ENOSPC, errno.EDQUOT):
                raise StorageCapacityError() from exc
            raise
