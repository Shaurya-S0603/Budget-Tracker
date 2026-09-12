# Student Expense Tracker

A dark-theme Streamlit expense tracker designed for **weekly category updates**.

## Monthly fund model

The app uses two separate pools:

- **Main Fund:** S$800 per month
- **Emergency Fund:** S$200 reserve

Normal spending is tracked against the S$800 Main Fund. Once monthly spending exceeds S$800, the excess is automatically treated as Emergency Fund usage.

The expense itself **keeps its real category** (Food, Transport, Personal, etc.). Emergency Fund is a funding source, not an expense category.

Whenever a weekly update causes monthly spending to exceed S$800, the app requires a reason before saving the update. The reason is stored with that week and shown on the Dashboard and Insights pages.

If spending exceeds S$1,000 in total, the app still records it but clearly flags the amount beyond all available funds.

## Weekly workflow

At the end of each week:

1. Open **Weekly Update**.
2. Pick a date in the week you are recording.
3. Enter the total spent for each category.
4. If the month remains within S$800, save normally.
5. If the month exceeds S$800, enter why the Emergency Fund is needed.
6. Click **Save weekly spending**.

Saving the same week again replaces the previous totals instead of double-counting them. Categories left at S$0 are not stored.

## Default category budgets

These allocations total the S$800 Main Fund:

- Food: S$570
- Personal: S$100
- Transportation: S$30
- Mobile and Services: S$55
- Air Con: S$45

Emergency Fund is intentionally excluded from category budgets.

## What it tracks

- Weekly spending by category
- Main Fund used and remaining
- Emergency Fund used and remaining
- Required reason for Emergency Fund usage
- Safe-to-spend per day from the Main Fund
- Monthly spending projection
- Category and weekly charts
- Budget warnings
- CSV export
- Re-import of the original workbook format

There are no income features.

## Run on Windows

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Or double-click `run.bat`.

## Run on macOS / Linux

```bash
./run.sh
```

## Data

The app stores working data in `data/expenses.db` using SQLite.

The original workbook can seed or re-import spending. Any old `Emergency Fund` rows from the workbook or earlier app versions are ignored because the reserve is no longer treated as a spending category.

To reset the local database, delete `data/expenses.db` and restart the app.
