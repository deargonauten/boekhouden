from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


def create_db_engine(settings: Settings) -> Engine:
    engine = create_engine(settings.database_url)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    with SessionLocal(bind=request.app.state.engine) as session:
        yield session
