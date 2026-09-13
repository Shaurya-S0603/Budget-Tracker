from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import db
import storage


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request, tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BUDGET_TRACKER_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.setattr(db, "DEFAULT_WORKBOOK", tmp_path / "missing.xlsx")
    # Tests never use the developer's Streamlit Secrets or production data.
    import streamlit as st
    monkeypatch.setattr(st, "secrets", {})
    admin = None
    pg = None
    schema = None
    if request.param == "postgresql":
        test_url = os.environ.get("TEST_DATABASE_URL")
        if not test_url:
            pgserver = pytest.importorskip("pgserver")
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                pytest.skip("Use TEST_DATABASE_URL for PostgreSQL tests when running as root.")
            pg = pgserver.get_server(tmp_path / "postgres", cleanup_mode="stop")
            test_url = pg.get_uri()
        url = make_url(test_url).set(drivername="postgresql+psycopg")
        admin = create_engine(url, isolation_level="AUTOCOMMIT")
        schema = "budget_test_" + uuid.uuid4().hex
        with admin.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
        monkeypatch.setenv("DATABASE_URL", isolated_url.render_as_string(hide_password=False))
    engine = storage.get_engine()
    try:
        yield request.param
    finally:
        engine.dispose()
        storage._engine.cache_clear()
        if admin:
            with admin.connect() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()
        if pg:
            pg.cleanup()
