from __future__ import annotations

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


def snapshot():
    result = json.loads(db.export_backup())
    return {table: sorted(json.dumps(row, sort_keys=True) for row in result[table])
            for table in ("expenses", "budgets", "emergency_uses")}


def test_data_survives_fresh_process_and_new_app_directory(database, tmp_path):
    db.init_db()
    db.upsert_weekly_expenses(DAY, {"Food": 810.25}, "Urgent replacement? S$10.25")
    db.upsert_budget("Food", 500)
    before = snapshot()
    env = os.environ.copy()
    if database == "postgresql":
        # A new deployment has no app-local database, uploads, or cache.
        env["BUDGET_TRACKER_DATA_DIR"] = str(tmp_path / "new-deployment")
    code = "import db; db.init_db(); print(db.export_backup().decode())"
    process = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                             check=True, text=True, capture_output=True, timeout=30)
    after = json.loads(process.stdout)
    assert before == {table: sorted(json.dumps(row, sort_keys=True) for row in after[table])
                      for table in before}


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
            writer, sheet_name="Transactions", header=False, index=False)
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
            writer, sheet_name="Transactions", header=False, index=False)
        pd.DataFrame([[None, "Food", None, 600]]).to_excel(
            writer, sheet_name="Summary", header=False, index=False)
    def fail_budget_write(*args):
        raise ValueError("Budget write interrupted")
    monkeypatch.setattr(db, "_replace_budgets", fail_budget_write)
    with pytest.raises(ValueError, match="interrupted"):
        db.import_workbook(BytesIO(workbook.getvalue()), replace=True)
    assert snapshot() == before


def test_overlapping_weekly_saves_do_not_mix_categories(database):
    db.init_db()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(db.upsert_weekly_expenses, DAY, amounts)
                   for amounts in ({"Food": 60, "Personal": 10}, {"Food": 90, "Books": 20})]
        for future in futures:
            future.result(timeout=20)
    totals = db.get_expenses().groupby("category")["amount"].sum().to_dict()
    assert totals in ({"Food": 60, "Personal": 10}, {"Food": 90, "Books": 20})


def test_existing_sqlite_is_migrated_only_once(database, tmp_path, monkeypatch):
    if database != "postgresql":
        pytest.skip("Requires a remote destination")
    destination = os.environ["DATABASE_URL"]
    monkeypatch.delenv("DATABASE_URL")
    db.init_db()
    db.upsert_budget("Food", 550)
    db.upsert_weekly_expenses(DAY, {"Food": 820.75}, "Essential replacement")
    before = snapshot()
    local_engine = storage.get_engine()
    local_engine.dispose()
    monkeypatch.setenv("DATABASE_URL", destination)
    db.init_db()
    assert snapshot() == before
    assert storage.local_db_path().exists()
    db.delete_week(db.week_period_key(DAY))
    db.delete_budget("Food")
    storage.get_engine().dispose()
    db.init_db()
    assert db.count_expenses() == 0
    assert "Food" not in db.get_budgets()


def test_unavailable_remote_never_falls_back_to_sqlite(tmp_path, monkeypatch):
    local_dir = tmp_path / "no-local-fallback"
    monkeypatch.setenv("BUDGET_TRACKER_DATA_DIR", str(local_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:do-not-expose@127.0.0.1:1/missing")
    with pytest.raises(storage.StorageError) as error:
        db.init_db()
    assert "do-not-expose" not in str(error.value)
    assert not (local_dir / "expenses.db").exists()


def test_streamlit_secret_selection_and_invalid_configuration(monkeypatch):
    import streamlit as st
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(st, "secrets", {"database": {"url": "postgresql://example/db"}})
    assert storage.configured_url() == "postgresql://example/db"
    monkeypatch.setenv("DATABASE_URL", "postgresql://environment/db")
    assert storage.configured_url() == "postgresql://environment/db"
    monkeypatch.setenv("DATABASE_URL", " ")
    with pytest.raises(storage.StorageError):
        storage.configured_url()
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setattr(st, "secrets", {"database": {}})
    with pytest.raises(storage.StorageError):
        storage.configured_url()


def test_old_sqlite_schema_is_upgraded_without_losing_records(tmp_path, monkeypatch):
    import streamlit as st
    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BUDGET_TRACKER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DEFAULT_WORKBOOK", tmp_path / "missing.xlsx")
    with sqlite3.connect(tmp_path / "expenses.db") as conn:
        conn.executescript("""
            CREATE TABLE expenses (id INTEGER PRIMARY KEY, expense_date TEXT,
              amount REAL NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL,
              payment_method TEXT NOT NULL DEFAULT '', is_essential INTEGER NOT NULL DEFAULT 0,
              source TEXT NOT NULL DEFAULT 'app', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE budgets (category TEXT PRIMARY KEY, monthly_budget REAL NOT NULL);
            INSERT INTO expenses (expense_date, amount, category) VALUES ('2026-09-01', 40, 'Food');
            INSERT INTO budgets VALUES ('Food', 550);
        """)
    db.init_db()
    assert db.count_expenses() == 1
    assert db.get_expenses().iloc[0]["entry_mode"] == "individual"
    assert db.get_budgets() == {"Food": 550}
