from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import DATABASE_URL


def _build_engine(url: str):
    kwargs: dict = {}
    if url.startswith("sqlite"):
        # check_same_thread: FastAPI's TestClient / threadpool touches the
        # connection from multiple threads. StaticPool keeps a single shared
        # connection so an in-memory DB survives across sessions.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url.rstrip("/") in ("sqlite:", "sqlite+pysqlite:"):
            kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    with SessionLocal() as session:
        yield session
