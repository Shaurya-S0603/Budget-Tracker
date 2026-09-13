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

## Persistent storage on Streamlit Cloud

**Connect a hosted PostgreSQL database so data survives Streamlit sleep, shutdowns,
restarts and redeployments.** Saving to the app's local filesystem alone does not
provide that guarantee. The app supports PostgreSQL providers such as Neon and
Supabase; Streamlit has an [official Neon setup guide](https://docs.streamlit.io/develop/tutorials/databases/neon).

1. If you already have expenses, first open **Weekly Update → Full backup and
   restore → Download full backup**. Keep this file before changing Secrets or
   rebooting the app. On the old version, download the spending CSV as a precaution
   before upgrading; it contains expenses and reasons, but not category budgets.
2. Create a PostgreSQL database, or use an existing one dedicated to this tracker.
   Copy its PostgreSQL connection URL. For Supabase, use its IPv4-compatible
   **Session pooler** connection URL when deploying on Streamlit Cloud.
3. Open your Streamlit app's **Settings → Secrets** and add:

   ```toml
   [database]
   url = "postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require"
   ```

   Replace the placeholder with the actual URL. Use the provider-generated URL
   with URL-encoded password characters. A template is included at
   `.streamlit/secrets.toml.example`. Never commit the real secret to GitHub.
4. Save the Secrets and reopen the app. Tables are created automatically. The
   sidebar will say **Cloud database** after a successful connection.
5. If your saved records are missing, use **Restore a full backup** to upload the
   backup from step 1. Check the totals, budgets and emergency reasons, then reboot
   the Streamlit app and check they are still there.

You can also provide the URL through the `DATABASE_URL` environment variable; it
takes precedence over `[database].url`. See Streamlit's
[Secrets management documentation](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

**The GitHub update alone does not activate cloud storage.** Until the connection
is configured, the app shows a **Local storage only** warning. A configured database
failure stops the operation with an error; it never silently switches to a new
local database or reports a successful save. Keep the hosted database itself active
and retain backups according to your provider's retention policy.

## Existing data and backups

- Local use continues to save to `data/expenses.db`. This survives stopping and
  restarting Streamlit on the same computer while that file is retained. Set
  `BUDGET_TRACKER_DATA_DIR` to choose a different directory or persistent volume.
- When PostgreSQL is initialized for the first time, an existing local database
  is copied in one transaction if it is still available on that machine. This
  preserves expenses, custom budgets, dates and emergency reasons. The original
  SQLite file is kept intact. An already-initialized PostgreSQL database is never
  automatically overwritten by an old local copy.
- If Streamlit has already erased its local database, the GitHub code cannot
  recover those entries. Restore a previously downloaded full backup or re-import
  the original workbook. CSV remains an export format, not a full restore format.
- Full JSON backups include all three data tables. Restoring over existing data
  requires the **Replace all saved data with this backup** checkbox. Restoration
  is atomic: validation or database errors leave the previous records intact.
- The original workbook at `data/NTU Monthly budget.xlsx` can seed a brand-new
  database or be manually re-imported. Startup seeds only once; deleting the last
  expense or budget no longer causes old records to reappear on a rerun/restart.
- Old `Emergency Fund` category rows remain excluded. The S$800 main fund and
  S$200 emergency reserve rules are unchanged.

All app sessions share this tracker and its database. It is intended for one
person's budget; use the hosting platform's access settings to control who can
open the app. Credentials, local databases, uploads and backups are gitignored.

## Verification

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

The tests exercise persistence across fresh Python processes, atomic weekly
replacement, backup validation/restore, deleted-data behavior, database failures,
and Streamlit navigation. To include real PostgreSQL integration tests on a
supported platform, install the test-only `pgserver` package and run the same
command. Each test uses isolated temporary data; `pgserver` is never a production
dependency or a substitute for hosted storage.
