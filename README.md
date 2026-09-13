# Student Expense Tracker

A dark-theme Streamlit budget tracker built around **weekly category totals**.

## Monthly fund model

The app uses two separate pools:

- **Main Fund:** S$800 per month
- **Emergency Fund:** S$200 reserve

Normal spending counts against the S$800 Main Fund. Once monthly spending exceeds S$800, the excess is treated as Emergency Fund usage. The expense keeps its real category, and the app requires a reason whenever a weekly update uses the reserve.

## Weekly workflow

1. Open **Weekly Update**.
2. Pick the week-ending date.
3. Enter the total spent in each category.
4. Save the week.
5. Re-saving the same ISO week replaces the old values instead of double-counting them.

Default category allocations total S$800:

- Food: S$570
- Personal: S$100
- Transportation: S$30
- Mobile and Services: S$55
- Air Con: S$45

Emergency Fund is a reserve, not an expense category.

## Persistence: GitHub autosave

The tracker uses one local SQLite database at `data/expenses.db`, then synchronizes that file with GitHub:

- Streamlit deploys the app from `main`.
- Persistent budget data is stored on the separate `budget-data` branch so saving an expense does **not** trigger a Streamlit redeployment.
- On app startup, the latest database file is downloaded from `budget-data` before SQLite opens.
- After every successful database write, the complete SQLite file is uploaded back to `budget-data`.
- Re-uploading an unchanged file does not create another commit.
- SQLite connections are serialized and short-lived to reduce lock/stale-connection problems in Streamlit sessions.
- If an upload fails after a local transaction commits, the local data is kept and the app reports a **GitHub autosave issue**.

This is intentionally simple for a single-user tracker. GitHub is not a high-write transactional database, so this design is appropriate for weekly/manual updates, not rapid multi-user writes.

### Streamlit Cloud setup

Create a **fine-grained GitHub personal access token** with **Contents: Read and write** permission for the repository that stores the database. Then add the following to **Streamlit Cloud → App settings → Secrets**:

```toml
[github]
token = "github_pat_REPLACE_ME"
repo = "Shaurya-S0603/Budget-Tracker"
branch = "budget-data"
db_path = "data/expenses.db"
```

A template is included at `.streamlit/secrets.toml.example`. Never commit the real token.

If an older Streamlit secret still says `branch = "main"`, this repository automatically maps that setting to `budget-data` for backward compatibility. Updating the secret to `budget-data` is still recommended for clarity.

You can also configure the same values through environment variables:

```text
BUDGET_TRACKER_GITHUB_TOKEN
BUDGET_TRACKER_GITHUB_REPO
BUDGET_TRACKER_GITHUB_BRANCH
BUDGET_TRACKER_GITHUB_DB_PATH
```

### Privacy warning

The SQLite database contains spending data. Keep the repository private, or point `[github].repo` to a private repository dedicated to the database.

The code does not store the GitHub token inside the SQLite file or the repository.

## Currency rendering

User-facing Markdown escapes the Singapore-dollar `$` character so Streamlit does not interpret currency text as LaTeX. Widgets that render plain text still display normal values such as `S$48.25`.

## Backups and imports

- **Download spending CSV** exports the spending table for inspection.
- **Download full backup** exports expenses, budgets, and Emergency Fund reasons as JSON.
- Full restore validates the backup before replacing existing data.
- The original workbook format can still be re-imported from **Weekly Update**.
- Existing `Emergency Fund` category rows are ignored because the reserve is a funding source, not a spending category.

## Run locally

### Windows

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Or double-click `run.bat`.

### macOS / Linux

```bash
./run.sh
```

Without a GitHub token the app still works locally and shows **Local storage** in the sidebar. The database remains on that computer at `data/expenses.db` unless `BUDGET_TRACKER_DATA_DIR` is set.

## Verification

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

The test suite covers weekly replacement, Emergency Fund validation, backup restore, concurrent local writes, GitHub upload/download behavior, autosave failures, schema upgrades, and Streamlit navigation.
