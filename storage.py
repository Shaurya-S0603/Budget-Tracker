"""SQLite storage with GitHub-backed autosave for Streamlit deployments."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from threading import RLock
from urllib.parse import quote

import requests
from requests import Response
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_GITHUB_REPO = "Shaurya-S0603/Budget-Tracker"
DEFAULT_GITHUB_BRANCH = "main"
DEFAULT_GITHUB_DB_PATH = "data/expenses.db"
GITHUB_API = "https://api.github.com"

_SYNC_LOCK = RLock()
_remote_loaded = False
_last_sync_error = ""


class StorageError(RuntimeError):
    """A safe storage message that never exposes tokens or budget data."""


def local_db_path() -> Path:
    directory = os.environ.get("BUDGET_TRACKER_DATA_DIR")
    root = Path(directory).expanduser().resolve() if directory else BASE_DIR / "data"
    return root / "expenses.db"


def _streamlit_github_secrets() -> dict[str, str]:
    try:
        import streamlit as st
        from streamlit.errors import StreamlitSecretNotFoundError

        try:
            if "github" not in st.secrets:
                return {}
            section = st.secrets["github"]
        except StreamlitSecretNotFoundError:
            return {}
        return {
            "token": str(section.get("token", "") or "").strip(),
            "repo": str(section.get("repo", "") or "").strip(),
            "branch": str(section.get("branch", "") or "").strip(),
            "db_path": str(section.get("db_path", "") or "").strip(),
        }
    except Exception as exc:
        if exc.__class__.__name__ == "StreamlitSecretNotFoundError":
            return {}
        raise StorageError("Check the [github] section in Streamlit Secrets.") from None


def github_config() -> dict[str, str | bool]:
    """Return GitHub autosave configuration without exposing the token."""
    secrets = _streamlit_github_secrets()
    token = (
        os.environ.get("BUDGET_TRACKER_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or secrets.get("token", "")
    )
    token = str(token or "").strip()

    repo = (
        os.environ.get("BUDGET_TRACKER_GITHUB_REPO")
        or secrets.get("repo")
        or DEFAULT_GITHUB_REPO
    )
    branch = (
        os.environ.get("BUDGET_TRACKER_GITHUB_BRANCH")
        or secrets.get("branch")
        or DEFAULT_GITHUB_BRANCH
    )
    db_path = (
        os.environ.get("BUDGET_TRACKER_GITHUB_DB_PATH")
        or secrets.get("db_path")
        or DEFAULT_GITHUB_DB_PATH
    )

    repo = str(repo).strip()
    branch = str(branch).strip()
    db_path = str(db_path).strip().lstrip("/")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise StorageError("GitHub autosave repo must use the owner/repository format.")
    if not branch:
        raise StorageError("GitHub autosave branch cannot be empty.")
    path_parts = Path(db_path).parts
    if not db_path or db_path.endswith("/") or ".." in path_parts:
        raise StorageError("GitHub autosave db_path must be a file path inside the repository.")

    return {
        "enabled": bool(token),
        "token": token,
        "repo": repo,
        "branch": branch,
        "db_path": db_path,
    }


def _github_url(config: dict[str, str | bool]) -> str:
    repo = str(config["repo"])
    path = quote(str(config["db_path"]), safe="/")
    return f"{GITHUB_API}/repos/{repo}/contents/{path}"


def _github_headers(config: dict[str, str | bool]) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {config['token']}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "budget-tracker-autosave",
    }


def _safe_request(method: str, config: dict[str, str | bool], **kwargs) -> Response:
    try:
        return requests.request(
            method,
            _github_url(config),
            headers=_github_headers(config),
            timeout=15,
            **kwargs,
        )
    except requests.RequestException:
        raise StorageError("GitHub autosave could not reach GitHub. Local data is still available.") from None


def _read_remote_file(config: dict[str, str | bool]) -> tuple[str | None, bytes | None]:
    response = _safe_request("GET", config, params={"ref": config["branch"]})
    if response.status_code == 404:
        return None, None
    if response.status_code != 200:
        raise StorageError(
            "GitHub autosave could not read the database file. Check the token, repo and branch permissions."
        )

    try:
        payload = response.json()
        sha = str(payload["sha"])
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise ValueError
        content = base64.b64decode(payload["content"], validate=False)
    except (KeyError, TypeError, ValueError):
        raise StorageError("GitHub returned an invalid database file response.") from None
    return sha, content


def _validate_sqlite_file(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size < 100:
            raise ValueError
        if path.read_bytes()[:16] != b"SQLite format 3\x00":
            raise ValueError
        uri = path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            result = conn.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError
    except (OSError, sqlite3.Error, ValueError):
        raise StorageError(
            "The GitHub autosave file is not a valid SQLite database. The local copy was not replaced."
        ) from None


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def sync_from_github() -> bool:
    """Load the latest database once per app process before opening SQLite."""
    global _remote_loaded, _last_sync_error
    with _SYNC_LOCK:
        if _remote_loaded:
            return False

        config = github_config()
        if not config["enabled"]:
            _remote_loaded = True
            return False

        _, content = _read_remote_file(config)
        if content is None:
            _remote_loaded = True
            _last_sync_error = ""
            return False

        target = local_db_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".github-download")
        try:
            temp.write_bytes(content)
            _validate_sqlite_file(temp)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)

        _remote_loaded = True
        _last_sync_error = ""
        return True


def sync_to_github() -> bool:
    """Upload the complete SQLite database after a committed local write."""
    global _last_sync_error
    config = github_config()
    if not config["enabled"]:
        return False

    with _SYNC_LOCK:
        path = local_db_path()
        if not path.exists():
            return False
        _validate_sqlite_file(path)
        content = path.read_bytes()
        remote_sha, _ = _read_remote_file(config)
        if remote_sha == _git_blob_sha(content):
            _last_sync_error = ""
            return False

        body = {
            "message": "chore(data): autosave budget tracker database",
            "content": base64.b64encode(content).decode("ascii"),
            "branch": config["branch"],
        }
        if remote_sha:
            body["sha"] = remote_sha

        response = _safe_request("PUT", config, json=body)
        if response.status_code not in {200, 201}:
            if response.status_code in {409, 422}:
                raise StorageError(
                    "GitHub autosave hit a concurrent update. Your data is saved locally; reload before editing again."
                )
            raise StorageError(
                "GitHub autosave could not upload the database. Your data is saved locally; check repository write access."
            )

        _last_sync_error = ""
        return True


def get_engine() -> Engine:
    sync_from_github()
    return _engine(str(local_db_path()))


@lru_cache(maxsize=4)
def _engine(local_path: str) -> Engine:
    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        "sqlite:///" + str(path),
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
        hide_parameters=True,
    )


def storage_status() -> dict[str, str | bool]:
    config = github_config()
    if not config["enabled"]:
        return {
            "persistent": False,
            "label": "Local storage",
            "message": (
                "GitHub autosave is not configured. Add a fine-grained GitHub token with Contents read/write "
                "access under [github] in Streamlit Secrets."
            ),
        }
    if _last_sync_error:
        return {
            "persistent": False,
            "label": "GitHub autosave issue",
            "message": _last_sync_error,
        }
    return {
        "persistent": True,
        "label": f"GitHub autosave · {config['branch']}",
        "message": "",
    }


@contextmanager
def connect(*, write: bool = False):
    """Run one SQLite transaction; successful writes are then autosaved to GitHub."""
    global _last_sync_error
    try:
        engine = get_engine()
        with engine.connect() as conn:
            with conn.begin():
                if write:
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    conn.exec_driver_sql("BEGIN")
                yield conn
    except StorageError:
        raise
    except SQLAlchemyError:
        raise StorageError(
            "The database operation could not be completed. Reload and check your saved data before retrying."
        ) from None

    if write:
        try:
            sync_to_github()
        except StorageError as exc:
            # The SQLite transaction has already committed. Keep that local success
            # and surface the sync problem on the next Streamlit render instead of
            # telling the user the database write failed when it did not.
            _last_sync_error = str(exc)


def _reset_sync_state_for_tests() -> None:
    global _remote_loaded, _last_sync_error
    _remote_loaded = False
    _last_sync_error = ""
