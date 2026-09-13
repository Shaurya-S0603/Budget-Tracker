"""Transactional storage, independent of Streamlit sessions and caches."""
from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

BASE_DIR = Path(__file__).resolve().parent


class StorageError(RuntimeError):
    """A safe message to show without exposing credentials or expense data."""


def configured_url() -> str:
    """Environment wins; the hosted app can instead use Streamlit Secrets."""
    value = os.environ.get("DATABASE_URL")
    if value is not None:
        if not value.strip():
            raise StorageError("DATABASE_URL is empty. Add your PostgreSQL connection URL.")
        return value.strip()

    import streamlit as st
    from streamlit.errors import StreamlitSecretNotFoundError

    try:
        if "database" not in st.secrets:
            return ""
        value = st.secrets["database"].get("url")
    except StreamlitSecretNotFoundError:
        return ""
    except Exception:
        raise StorageError("Check the database section in Streamlit Secrets.") from None
    if not isinstance(value, str) or not value.strip():
        raise StorageError("Add a non-empty url under [database] in Streamlit Secrets.")
    return value.strip()


def local_db_path() -> Path:
    directory = os.environ.get("BUDGET_TRACKER_DATA_DIR")
    return (Path(directory).expanduser().resolve() if directory else BASE_DIR / "data") / "expenses.db"


def get_engine() -> Engine:
    return _engine(configured_url(), str(local_db_path()))


@lru_cache(maxsize=4)
def _engine(raw_url: str, local_path: str) -> Engine:
    if not raw_url:
        path = Path(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return create_engine(
            "sqlite:///" + str(path),
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
            hide_parameters=True,
        )
    try:
        url = make_url(raw_url)
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError("unsupported database")
        url = url.set(drivername="postgresql+psycopg")
        # Hosted database providers require TLS. Keep Unix sockets/localhost
        # available for development and the PostgreSQL integration tests.
        if url.host and url.host not in {"localhost", "127.0.0.1", "::1"}:
            if "sslmode" not in url.query:
                url = url.update_query_dict({"sslmode": "require"})
        return create_engine(
            url,
            connect_args={"connect_timeout": 10, "prepare_threshold": None},
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=2,
            max_overflow=3,
            pool_timeout=15,
            hide_parameters=True,
        )
    except (SQLAlchemyError, ValueError, ImportError):
        raise StorageError("Check your PostgreSQL connection URL and installed requirements.") from None


def storage_status() -> dict[str, str | bool]:
    remote = get_engine().dialect.name == "postgresql"
    return {"persistent": remote, "label": "Cloud database" if remote else "Local storage"}


@contextmanager
def connect(*, write: bool = False):
    """Commit before returning success; roll back an entire failed operation.

    Serialize writers so overlapping sessions cannot validate emergency spending
    against stale monthly totals or race during initial seeding/restoration.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            with conn.begin():
                if write:
                    if engine.dialect.name == "postgresql":
                        conn.execute(text("SET LOCAL lock_timeout = '15s'"))
                        conn.execute(text("SELECT pg_advisory_xact_lock(800200)"))
                    else:
                        conn.exec_driver_sql("BEGIN IMMEDIATE")
                elif engine.dialect.name == "postgresql":
                    # A backup's tables must all reflect the same committed state.
                    conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                else:
                    # sqlite3's legacy mode does not start a transaction for SELECT.
                    conn.exec_driver_sql("BEGIN")
                yield conn
    except SQLAlchemyError:
        raise StorageError(
            "The database operation could not be confirmed. Check the database connection, "
            "then reload to check your saved data before retrying."
        ) from None
