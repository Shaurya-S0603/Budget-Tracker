from __future__ import annotations

import calendar
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "expenses.db"
DEFAULT_WORKBOOK = DATA_DIR / "NTU Monthly budget.xlsx"

MAIN_FUND_LIMIT = 800.0
EMERGENCY_FUND_LIMIT = 200.0

DEFAULT_BUDGETS = {
    "Food": 570.0,
    "Personal": 100.0,
    "Transportation": 30.0,
    "Mobile and Services": 55.0,
    "Air Con": 45.0,
}

RESERVED_CATEGORIES = {"Emergency Fund"}
RESERVED_CATEGORY_KEYS = {category.casefold() for category in RESERVED_CATEGORIES}

ESSENTIAL_DEFAULTS = {
    "Food", "Transportation", "Mobile and Services", "Air Con"
}


def _is_reserved_category(category: object) -> bool:
    return str(category).strip().casefold() in RESERVED_CATEGORY_KEYS


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _month_spend_total(conn: sqlite3.Connection, target_date: date) -> float:
    """Return spend for target month, including undated legacy seed rows only
    when target_date is in the current month.
    """
    month_key = _month_key(target_date)
    current_month_key = _month_key(date.today())
    if month_key == current_month_key:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM expenses
            WHERE lower(trim(category)) != 'emergency fund'
              AND (
                    substr(expense_date, 1, 7) = ?
                    OR (expense_date IS NULL AND entry_mode = 'legacy')
                  )
            """,
            (month_key,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM expenses
            WHERE lower(trim(category)) != 'emergency fund'
              AND substr(expense_date, 1, 7) = ?
            """,
            (month_key,),
        ).fetchone()
    return float(row[0] or 0.0)


def fund_status(total_spent: float) -> dict[str, float]:
    total_spent = max(float(total_spent or 0.0), 0.0)
    main_used = min(total_spent, MAIN_FUND_LIMIT)
    main_remaining = max(MAIN_FUND_LIMIT - total_spent, 0.0)
    emergency_required = max(total_spent - MAIN_FUND_LIMIT, 0.0)
    emergency_used = min(emergency_required, EMERGENCY_FUND_LIMIT)
    emergency_remaining = max(EMERGENCY_FUND_LIMIT - emergency_used, 0.0)
    over_total_funds = max(
        total_spent - MAIN_FUND_LIMIT - EMERGENCY_FUND_LIMIT, 0.0
    )
    return {
        "total_spent": total_spent,
        "main_used": main_used,
        "main_remaining": main_remaining,
        "main_utilization": (
            total_spent / MAIN_FUND_LIMIT * 100 if MAIN_FUND_LIMIT else 0.0
        ),
        "emergency_used": emergency_used,
        "emergency_remaining": emergency_remaining,
        "over_total_funds": over_total_funds,
        "total_available": MAIN_FUND_LIMIT + EMERGENCY_FUND_LIMIT,
    }


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_date TEXT,
                amount REAL NOT NULL CHECK(amount >= 0),
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                payment_method TEXT NOT NULL DEFAULT '',
                is_essential INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'app',
                entry_mode TEXT NOT NULL DEFAULT 'individual',
                period_key TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS budgets (
                category TEXT PRIMARY KEY,
                monthly_budget REAL NOT NULL CHECK(monthly_budget >= 0)
            );

            CREATE TABLE IF NOT EXISTS emergency_uses (
                period_key TEXT PRIMARY KEY,
                expense_date TEXT NOT NULL,
                emergency_used_after REAL NOT NULL DEFAULT 0,
                reason TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cols = _columns(conn, "expenses")
        if "entry_mode" not in cols:
            conn.execute(
                "ALTER TABLE expenses ADD COLUMN entry_mode TEXT NOT NULL DEFAULT 'individual'"
            )
        if "period_key" not in cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN period_key TEXT")

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_category_period
            ON expenses(period_key, category)
            WHERE entry_mode = 'weekly' AND period_key IS NOT NULL
            """
        )

        # Old versions treated Emergency Fund as a budget/expense category.
        # It is now a funding reserve, so remove any stale category rows.
        conn.execute(
            "DELETE FROM expenses WHERE lower(trim(category)) = 'emergency fund'"
        )
        conn.execute(
            "DELETE FROM budgets WHERE lower(trim(category)) = 'emergency fund'"
        )

    if not get_budgets():
        replace_budgets(DEFAULT_BUDGETS)

    if count_expenses() == 0 and DEFAULT_WORKBOOK.exists():
        import_workbook(DEFAULT_WORKBOOK, replace=True)


def count_expenses() -> int:
    with _connect() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM expenses "
                "WHERE lower(trim(category)) != 'emergency fund'"
            ).fetchone()[0]
        )


def get_expenses() -> pd.DataFrame:
    with _connect() as conn:
        df = pd.read_sql_query(
            """
            SELECT id, expense_date, amount, description, category,
                   payment_method, is_essential, source, entry_mode,
                   period_key, created_at
            FROM expenses
            WHERE lower(trim(category)) != 'emergency fund'
            ORDER BY
              CASE WHEN expense_date IS NULL OR expense_date = '' THEN 1 ELSE 0 END,
              expense_date DESC,
              id DESC
            """,
            conn,
        )
    if df.empty:
        return pd.DataFrame(
            columns=[
                "id", "expense_date", "amount", "description", "category",
                "payment_method", "is_essential", "source", "entry_mode",
                "period_key", "created_at", "date",
            ]
        )
    df["date"] = pd.to_datetime(df["expense_date"], errors="coerce")
    df["is_essential"] = df["is_essential"].astype(bool)
    return df


def get_emergency_uses() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            SELECT period_key, expense_date, emergency_used_after, reason, updated_at
            FROM emergency_uses
            ORDER BY expense_date DESC, period_key DESC
            """,
            conn,
        )


def week_period_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def upsert_weekly_expenses(
    week_ending: date,
    amounts: dict[str, float],
    emergency_reason: str = "",
) -> dict:
    """Replace category totals for one ISO week.

    When the month's spending exceeds the S$800 main fund, the excess is
    considered Emergency Fund usage. A reason is required for that save.
    """
    period_key = week_period_key(week_ending)
    cleaned = {
        str(category).strip(): max(float(amount or 0), 0.0)
        for category, amount in amounts.items()
        if str(category).strip() and not _is_reserved_category(category)
    }

    with _connect() as conn:
        old_reason_row = conn.execute(
            "SELECT reason FROM emergency_uses WHERE period_key = ?",
            (period_key,),
        ).fetchone()
        old_reason = str(old_reason_row["reason"]).strip() if old_reason_row else ""

        conn.execute(
            "DELETE FROM expenses WHERE entry_mode = 'weekly' AND period_key = ?",
            (period_key,),
        )

        inserted = 0
        weekly_total = 0.0
        for category, amount in cleaned.items():
            if amount <= 0:
                continue
            conn.execute(
                """
                INSERT INTO expenses
                (expense_date, amount, description, category, payment_method,
                 is_essential, source, entry_mode, period_key)
                VALUES (?, ?, ?, ?, '', ?, 'weekly', 'weekly', ?)
                """,
                (
                    week_ending.isoformat(),
                    amount,
                    f"Weekly total · {period_key}",
                    category,
                    int(category in ESSENTIAL_DEFAULTS),
                    period_key,
                ),
            )
            inserted += 1
            weekly_total += amount

        month_total = _month_spend_total(conn, week_ending)
        status = fund_status(month_total)

        if status["emergency_used"] > 0:
            reason = emergency_reason.strip() or old_reason
            if not reason:
                raise ValueError(
                    "A reason is required because this update uses the Emergency Fund."
                )
            conn.execute(
                """
                INSERT INTO emergency_uses
                    (period_key, expense_date, emergency_used_after, reason, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(period_key) DO UPDATE SET
                    expense_date = excluded.expense_date,
                    emergency_used_after = excluded.emergency_used_after,
                    reason = excluded.reason,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    period_key,
                    week_ending.isoformat(),
                    status["emergency_used"],
                    reason,
                ),
            )
        else:
            conn.execute(
                "DELETE FROM emergency_uses WHERE period_key = ?",
                (period_key,),
            )
            # If the month is back below the main-fund ceiling after a correction,
            # no Emergency Fund explanation for that month should remain.
            conn.execute(
                "DELETE FROM emergency_uses WHERE substr(expense_date, 1, 7) = ?",
                (_month_key(week_ending),),
            )

    return {
        "period_key": period_key,
        "categories_saved": inserted,
        "weekly_total": weekly_total,
        "month_total": month_total,
        **status,
    }


def get_weekly_totals() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            SELECT
                e.period_key,
                MAX(e.expense_date) AS week_ending,
                SUM(e.amount) AS total_spent,
                COUNT(*) AS categories_recorded,
                MAX(u.reason) AS emergency_reason
            FROM expenses e
            LEFT JOIN emergency_uses u ON u.period_key = e.period_key
            WHERE e.entry_mode = 'weekly'
              AND e.period_key IS NOT NULL
              AND lower(trim(e.category)) != 'emergency fund'
            GROUP BY e.period_key
            ORDER BY e.period_key DESC
            """,
            conn,
        )


def delete_week(period_key: str) -> None:
    with _connect() as conn:
        date_row = conn.execute(
            """
            SELECT MAX(expense_date) AS expense_date
            FROM expenses
            WHERE entry_mode = 'weekly' AND period_key = ?
            """,
            (period_key,),
        ).fetchone()
        expense_date = date_row["expense_date"] if date_row else None

        conn.execute(
            "DELETE FROM expenses WHERE entry_mode = 'weekly' AND period_key = ?",
            (period_key,),
        )
        conn.execute(
            "DELETE FROM emergency_uses WHERE period_key = ?",
            (period_key,),
        )

        if expense_date:
            target_date = date.fromisoformat(str(expense_date)[:10])
            month_total = _month_spend_total(conn, target_date)
            if month_total <= MAIN_FUND_LIMIT:
                conn.execute(
                    "DELETE FROM emergency_uses WHERE substr(expense_date, 1, 7) = ?",
                    (_month_key(target_date),),
                )


def delete_expenses(ids: Iterable[int]) -> None:
    ids = [int(x) for x in ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        conn.execute(f"DELETE FROM expenses WHERE id IN ({placeholders})", ids)


def get_budgets() -> dict[str, float]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT category, monthly_budget
            FROM budgets
            WHERE lower(trim(category)) != 'emergency fund'
            ORDER BY category
            """
        ).fetchall()
    return {str(r["category"]): float(r["monthly_budget"]) for r in rows}


def replace_budgets(budgets: dict[str, float]) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM budgets")
        conn.executemany(
            "INSERT INTO budgets(category, monthly_budget) VALUES (?, ?)",
            [
                (str(k).strip(), max(float(v), 0.0))
                for k, v in budgets.items()
                if str(k).strip() and not _is_reserved_category(k)
            ],
        )


def upsert_budget(category: str, monthly_budget: float) -> None:
    category = category.strip()
    if _is_reserved_category(category):
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO budgets(category, monthly_budget)
            VALUES (?, ?)
            ON CONFLICT(category) DO UPDATE SET monthly_budget = excluded.monthly_budget
            """,
            (category, max(float(monthly_budget), 0.0)),
        )


def delete_budget(category: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM budgets WHERE category = ?", (category,))


def import_workbook(path: str | Path, replace: bool = False) -> dict:
    """Import spendable expenses and category budgets from the workbook.

    Emergency Fund rows are skipped because the S$200 reserve is a funding
    source that is only drawn after the S$800 main fund is exhausted.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    raw_tx = pd.read_excel(path, sheet_name="Transactions", header=None)
    rows = []
    reserved_rows_skipped = 0

    for _, row in raw_tx.iterrows():
        if len(row) < 5:
            continue
        amount = pd.to_numeric(row.iloc[2], errors="coerce")
        category = row.iloc[4]
        if pd.isna(amount) or pd.isna(category):
            continue
        category = str(category).strip()
        if not category or category.lower() == "category":
            continue
        if _is_reserved_category(category):
            reserved_rows_skipped += 1
            continue

        parsed_date = pd.to_datetime(row.iloc[1], errors="coerce")
        expense_date = None if pd.isna(parsed_date) else parsed_date.date()
        description = "" if pd.isna(row.iloc[3]) else str(row.iloc[3]).strip()
        rows.append((expense_date, float(abs(amount)), description, category))

    budgets: dict[str, float] = {}
    try:
        raw_summary = pd.read_excel(path, sheet_name="Summary", header=None)
        for _, row in raw_summary.iterrows():
            if len(row) < 4:
                continue
            category = row.iloc[1]
            budget = pd.to_numeric(row.iloc[3], errors="coerce")
            if pd.isna(category) or pd.isna(budget):
                continue
            category = str(category).strip()
            if category in DEFAULT_BUDGETS:
                budgets[category] = float(budget)
    except Exception:
        budgets = {}

    with _connect() as conn:
        if replace:
            conn.execute("DELETE FROM expenses")
            conn.execute("DELETE FROM emergency_uses")
        else:
            conn.execute(
                "DELETE FROM expenses WHERE lower(trim(category)) = 'emergency fund'"
            )

        for expense_date, amount, description, category in rows:
            conn.execute(
                """
                INSERT INTO expenses
                (expense_date, amount, description, category, payment_method,
                 is_essential, source, entry_mode, period_key)
                VALUES (?, ?, ?, ?, '', ?, 'excel', 'legacy', NULL)
                """,
                (
                    expense_date.isoformat() if expense_date else None,
                    amount,
                    description,
                    category,
                    int(category in ESSENTIAL_DEFAULTS),
                ),
            )

    if budgets:
        replace_budgets(budgets)

    return {
        "expenses_imported": len(rows),
        "budget_categories_imported": len(budgets),
        "undated_expenses": sum(1 for r in rows if r[0] is None),
        "reserved_rows_skipped": reserved_rows_skipped,
    }


def current_cycle_expenses(
    df: pd.DataFrame,
    today: date | None = None,
) -> pd.DataFrame:
    """Current month plus undated legacy spreadsheet entries."""
    if df.empty:
        return df.copy()

    today = today or date.today()
    dated_current = (
        df["date"].notna()
        & (df["date"].dt.year == today.year)
        & (df["date"].dt.month == today.month)
    )
    undated_legacy = df["date"].isna() & (df["entry_mode"] == "legacy")
    return df[dated_current | undated_legacy].copy()


def week_label(row: pd.Series) -> str:
    period = row.get("period_key")
    if isinstance(period, str) and period:
        return period
    if pd.notna(row.get("date")):
        d = row["date"]
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    text = str(row.get("description", ""))
    match = re.search(r"week\s*(\d+)", text, flags=re.I)
    if match:
        return f"Week {match.group(1)}"
    return "Legacy / undated"


def month_days(today: date | None = None) -> tuple[int, int, int]:
    today = today or date.today()
    days_total = calendar.monthrange(today.year, today.month)[1]
    elapsed = today.day
    remaining_including_today = days_total - today.day + 1
    return days_total, elapsed, remaining_including_today
