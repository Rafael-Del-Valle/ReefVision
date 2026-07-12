"""FastAPI dependencies."""

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield a session from the current application instance."""

    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session
