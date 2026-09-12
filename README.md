# Student Expense Tracker

A dark-theme Streamlit expense tracker designed for **weekly category updates**.

## Weekly workflow

At the end of each week:

1. Open **Weekly Update**.
2. Pick a date in the week you are recording.
3. Enter the **total spent for each category** that week.
4. Click **Save weekly spending**.

You do **not** need to enter every purchase separately.

If you save the same week again, the app replaces that week's previous totals instead of double-counting them. Categories left at S$0 are simply not stored for that week.

## Monthly money structure

The tracker treats **S$800 per month as the actual spendable budget**.

The separate **S$200 Emergency Fund is a reserve**, not an expense category and not spendable monthly money. It is excluded from:

- expense totals
- budget utilization
- weekly entry
- charts and insights
- safe-to-spend calculations
- workbook imports

Existing local databases are automatically cleaned on startup so any old `Emergency Fund` budget or expense rows are removed from tracking.

## What it tracks

- Weekly spending by category
- Total monthly expenses
- Monthly and category budgets
- Remaining budget
- Safe-to-spend per day
- Monthly spending projection
- Category and weekly charts
- Budget warnings
- CSV export
- Re-import of the original workbook format

There are **no income features**.

## Run on Windows

1. Install Python 3.11+.
2. Open this folder in VS Code or File Explorer.
3. Double-click `run.bat`.

Or use the terminal:

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Run on macOS / Linux

```bash
./run.sh
```

## Data

The first run imports the bundled `NTU Monthly budget.xlsx` into `data/expenses.db` (SQLite). After that, weekly updates are stored locally in SQLite.

The source workbook's starting expense rows have blank dates. The app preserves them as **legacy / undated** expenses and includes them in the current starting budget instead of inventing dates.

### Starting values from the workbook

The workbook originally allocates S$1,000 across categories, but S$200 of that is the Emergency Fund reserve. The tracker therefore uses only the remaining S$800 as the spending budget.

- Spendable monthly budget: **S$800.00**
- Emergency Fund reserve: **S$200.00**
- Recorded starting expenses: **S$430.90**
- Remaining spendable budget: **S$369.10**

Spendable category budgets:

- Food: S$570
- Personal: S$100
- Transportation: S$30
- Mobile and Services: S$55
- Air Con: S$45

These add up to **S$800**. The Emergency Fund is intentionally kept outside the expense tracker.

## Reset to the workbook

Delete `data/expenses.db` and restart the app. It will seed itself from the included workbook again, automatically excluding the Emergency Fund from spending data and budgets.
