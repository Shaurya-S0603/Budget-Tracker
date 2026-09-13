from __future__ import annotations

import pytest

import db
import storage


@pytest.fixture
def database(tmp_path, monkeypatch):
    """Use an isolated local SQLite database with GitHub sync disabled."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("BUDGET_TRACKER_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("BUDGET_TRACKER_GITHUB_REPO", raising=False)
    monkeypatch.delenv("BUDGET_TRACKER_GITHUB_BRANCH", raising=False)
    monkeypatch.delenv("BUDGET_TRACKER_GITHUB_DB_PATH", raising=False)
    monkeypatch.setenv("BUDGET_TRACKER_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.setattr(db, "DEFAULT_WORKBOOK", tmp_path / "missing.xlsx")

    import streamlit as st

    monkeypatch.setattr(st, "secrets", {})
    storage._engine.cache_clear()
    storage._reset_sync_state_for_tests()
    engine = storage.get_engine()
    try:
        yield "sqlite"
    finally:
        engine.dispose()
        storage._engine.cache_clear()
        storage._reset_sync_state_for_tests()
