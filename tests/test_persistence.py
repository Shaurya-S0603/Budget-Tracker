from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

import db
import storage

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 9, 13)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def snapshot():
    result = json.loads(db.export_backup())
    return {
        table: sorted(json.dumps(row, sort_keys=True) for row in result[table])
        for table in ("expenses", "budgets", "emergency_uses")
    }


def test_data_survives_fresh_process(database):
    db.init_db()
    db.upsert_weekly_expenses(DAY, {"Food": 810.25}, "Urgent replacement? S$10.25")
    db.upsert_budget("Food", 500)
    before = snapshot()

    code = "import db; db.init_db(); print(db.export_backup().decode())"
    process = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=os.environ.copy(),
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    )
    after = json.loads(process.stdout)
    assert before == {
        table: sorted(json.dumps(row, sort_keys=True) for row in after[table])
        for table in before
    }


def test_week_replacement_and_reason_validation_are_atomic(database):
    db.init_db()
    db.upsert_weekly_expenses(DAY, {"Food": 400, "Personal": 20})
    before = snapshot()
    with pytest.raises(ValueError, match="reason"):
        db.upsert_weekly_expenses(DAY, {"Food": 850})
    assert snapshot() == before

    db.upsert_weekly_expenses(DAY, {"Food": 850}, "Essential repair")
    db.upsert_weekly_expenses(DAY, {"Food": 875})
    assert db.count_expenses() == 1
    assert db.get_emergency_uses().iloc[0]["reason"] == "Essential repair"

    db.upsert_weekly_expenses(DAY, {"Food": 200})
    assert db.get_emergency_uses().empty


def test_empty_data_is_not_reseeded_on_restart(database, tmp_path, monkeypatch):
    workbook = tmp_path / "seed.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame([[None, "2026-09-01", 50, "Seed", "Food"]]).to_excel(
            writer, sheet_name="Transactions", header=False, index=False
        )
    monkeypatch.setattr(db, "DEFAULT_WORKBOOK", workbook)
    db.init_db()
    assert db.count_expenses() == 1

    db.delete_expenses(db.get_expenses()["id"])
    db.replace_budgets({})
    storage.get_engine().dispose()
    db.init_db()
    assert db.count_expenses() == 0
    assert db.get_budgets() == {}


def test_complete_backup_restore_and_overwrite_guard(database):
    db.init_db()
    db.upsert_budget("Books", 70)
    db.upsert_weekly_expenses(DAY, {"Food": 900}, "Required replacement")
    before = snapshot()
    backup = db.export_backup()

    with pytest.raises(ValueError, match="Confirm replacement"):
        db.restore_backup(backup)
    assert snapshot() == before

    db.delete_week(db.week_period_key(DAY))
    db.restore_backup(backup, replace=True)
    assert snapshot() == before
    db.init_db()
    assert snapshot() == before


@pytest.mark.parametrize("damage", ["amount", "duplicate", "table", "version"])
def test_invalid_backup_never_replaces_data(database, damage):
    db.init_db()
    db.upsert_weekly_expenses(DAY, {"Food": 90})
    before = snapshot()
    backup = json.loads(db.export_backup())
    if damage == "amount":
        backup["expenses"][0]["amount"] = float("nan")
    elif damage == "duplicate":
        backup["expenses"].append(backup["expenses"][0].copy())
    elif damage == "table":
        del backup["budgets"]
    else:
        backup["version"] = 99

    with pytest.raises(ValueError):
        db.restore_backup(json.dumps(backup).encode(), replace=True)
    assert snapshot() == before


def test_workbook_expenses_and_budgets_rollback_together(database, monkeypatch):
    db.init_db()
    db.upsert_weekly_expenses(DAY, {"Food": 100})
    before = snapshot()
    workbook = BytesIO()
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame([[None, "2026-09-13", 80, "Import", "Food"]]).to_excel(
            writer, sheet_name="Transactions", header=False, index=False
        )
        pd.DataFrame([[None, "Food", None, 600]]).to_excel(
            writer, sheet_name="Summary", header=False, index=False
        )

    def fail_budget_write(*args):
        raise ValueError("Budget write interrupted")

    monkeypatch.setattr(db, "_replace_budgets", fail_budget_write)
    with pytest.raises(ValueError, match="interrupted"):
        db.import_workbook(BytesIO(workbook.getvalue()), replace=True)
    assert snapshot() == before


def test_overlapping_weekly_saves_do_not_mix_categories(database):
    db.init_db()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(db.upsert_weekly_expenses, DAY, amounts)
            for amounts in (
                {"Food": 60, "Personal": 10},
                {"Food": 90, "Books": 20},
            )
        ]
        for future in futures:
            future.result(timeout=20)
    totals = db.get_expenses().groupby("category")["amount"].sum().to_dict()
    assert totals in (
        {"Food": 60, "Personal": 10},
        {"Food": 90, "Books": 20},
    )


def test_github_upload_creates_remote_database(database, monkeypatch):
    db.init_db()
    db.upsert_weekly_expenses(DAY, {"Food": 48.25})
    monkeypatch.setenv("BUDGET_TRACKER_GITHUB_TOKEN", "test-token")

    calls = []

    def fake_request(method, config, **kwargs):
        calls.append((method, kwargs))
        if method == "GET":
            return FakeResponse(404)
        if method == "PUT":
            content = base64.b64decode(kwargs["json"]["content"])
            assert content.startswith(b"SQLite format 3\x00")
            assert kwargs["json"]["branch"] == "budget-data"
            return FakeResponse(201, {"content": {"sha": "new"}})
        raise AssertionError(method)

    monkeypatch.setattr(storage, "_safe_request", fake_request)
    assert storage.sync_to_github() is True
    assert [method for method, _ in calls] == ["GET", "PUT"]
    assert storage.storage_status()["persistent"] is True


def test_github_download_restores_database_in_new_directory(database, tmp_path, monkeypatch):
    db.init_db()
    db.upsert_budget("Books", 77)
    db.upsert_weekly_expenses(DAY, {"Food": 123.45})
    source = storage.local_db_path().read_bytes()
    source_sha = storage._git_blob_sha(source)

    storage.get_engine().dispose()
    storage._engine.cache_clear()
    monkeypatch.setenv("BUDGET_TRACKER_DATA_DIR", str(tmp_path / "new-deployment"))
    monkeypatch.setenv("BUDGET_TRACKER_GITHUB_TOKEN", "test-token")
    storage._reset_sync_state_for_tests()

    def fake_request(method, config, **kwargs):
        assert method == "GET"
        return FakeResponse(
            200,
            {
                "sha": source_sha,
                "encoding": "base64",
                "content": base64.b64encode(source).decode("ascii"),
            },
        )

    monkeypatch.setattr(storage, "_safe_request", fake_request)
    db.init_db()
    assert float(db.get_expenses()["amount"].sum()) == 123.45
    assert db.get_budgets()["Books"] == 77
    assert storage.local_db_path().parent.name == "new-deployment"


def test_failed_github_sync_keeps_committed_local_write(database, monkeypatch):
    db.init_db()
    monkeypatch.setenv("BUDGET_TRACKER_GITHUB_TOKEN", "test-token")

    def fake_request(method, config, **kwargs):
        return FakeResponse(500)

    monkeypatch.setattr(storage, "_safe_request", fake_request)
    db.upsert_budget("Books", 55)
    assert db.get_budgets()["Books"] == 55
    status = storage.storage_status()
    assert status["persistent"] is False
    assert status["label"] == "GitHub autosave issue"


def test_streamlit_secret_selection_and_invalid_configuration(monkeypatch):
    import streamlit as st

    for key in (
        "GITHUB_TOKEN",
        "BUDGET_TRACKER_GITHUB_TOKEN",
        "BUDGET_TRACKER_GITHUB_REPO",
        "BUDGET_TRACKER_GITHUB_BRANCH",
        "BUDGET_TRACKER_GITHUB_DB_PATH",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(
        st,
        "secrets",
        {
            "github": {
                "token": "secret-token",
                "repo": "owner/repo",
                "branch": "budget-data",
                "db_path": "state/expenses.db",
            }
        },
    )
    config = storage.github_config()
    assert config["enabled"] is True
    assert config["repo"] == "owner/repo"
    assert config["branch"] == "budget-data"
    assert config["db_path"] == "state/expenses.db"

    # Backward compatibility: our earlier setup instructions told Streamlit to
    # use main. For the Budget Tracker repo that now maps to budget-data so a
    # save cannot trigger a redeployment loop.
    monkeypatch.setattr(
        st,
        "secrets",
        {
            "github": {
                "token": "secret-token",
                "repo": "Shaurya-S0603/Budget-Tracker",
                "branch": "main",
                "db_path": "data/expenses.db",
            }
        },
    )
    assert storage.github_config()["branch"] == "budget-data"

    monkeypatch.setenv("BUDGET_TRACKER_GITHUB_REPO", "not valid")
    with pytest.raises(storage.StorageError):
        storage.github_config()


def test_old_sqlite_schema_is_upgraded_without_losing_records(tmp_path, monkeypatch):
    import streamlit as st

    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("BUDGET_TRACKER_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("BUDGET_TRACKER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DEFAULT_WORKBOOK", tmp_path / "missing.xlsx")
    storage._engine.cache_clear()
    storage._reset_sync_state_for_tests()

    with sqlite3.connect(tmp_path / "expenses.db") as conn:
        conn.executescript(
            """
            CREATE TABLE expenses (id INTEGER PRIMARY KEY, expense_date TEXT,
              amount REAL NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL,
              payment_method TEXT NOT NULL DEFAULT '', is_essential INTEGER NOT NULL DEFAULT 0,
              source TEXT NOT NULL DEFAULT 'app', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE budgets (category TEXT PRIMARY KEY, monthly_budget REAL NOT NULL);
            INSERT INTO expenses (expense_date, amount, category) VALUES ('2026-09-01', 40, 'Food');
            INSERT INTO budgets VALUES ('Food', 550);
            """
        )

    db.init_db()
    assert db.count_expenses() == 1
    assert db.get_expenses().iloc[0]["entry_mode"] == "individual"
    assert db.get_budgets() == {"Food": 550}
