from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

from db import (
    EMERGENCY_FUND_LIMIT,
    MAIN_FUND_LIMIT,
    current_cycle_expenses,
    delete_budget,
    delete_week,
    export_backup,
    fund_status,
    get_budgets,
    get_emergency_uses,
    get_expenses,
    get_weekly_totals,
    import_workbook,
    init_db,
    month_days,
    restore_backup,
    upsert_budget,
    upsert_weekly_expenses,
    week_label,
)
from storage import StorageError, storage_status

st.set_page_config(
    page_title="Student Expense Tracker",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
:root{--bg:#090c10;--panel:#11161d;--border:#27313d;--text:#f3f6f9;--muted:#8d99a6;--green:#39d98a;--amber:#f4b860;--red:#ff6b6b}
.stApp{background:var(--bg);color:var(--text)}
[data-testid="stSidebar"]{background:#0d1117;border-right:1px solid var(--border)}
[data-testid="stHeader"]{background:rgba(9,12,16,.85)}
.block-container{padding-top:1.5rem;max-width:1450px}
.kpi{background:linear-gradient(180deg,#141a22 0%,#10151c 100%);border:1px solid var(--border);border-radius:18px;padding:18px 20px;min-height:120px}
.kpi .label{color:var(--muted);font-size:.8rem;font-weight:650;text-transform:uppercase;letter-spacing:.07em}
.kpi .value{color:var(--text);font-size:2rem;font-weight:800;margin-top:7px}
.kpi .hint{color:var(--muted);font-size:.78rem;margin-top:5px}
.kpi.good .value{color:var(--green)}.kpi.warn .value{color:var(--amber)}.kpi.bad .value{color:var(--red)}
[data-testid="stMetric"]{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:14px 16px}
.stButton>button,.stDownloadButton>button{border-radius:10px;border:1px solid #33404e;font-weight:700}
.stButton>button[kind="primary"]{background:#2cb67d;color:#04120d;border:none}
div[data-baseweb="input"]>div,div[data-baseweb="select"]>div,textarea{background-color:#11161d!important;border-color:#2a3440!important}
[data-testid="stDataFrame"]{border:1px solid var(--border);border-radius:14px;overflow:hidden}
</style>
""",
    unsafe_allow_html=True,
)

def storage_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except StorageError as exc:
        st.error(str(exc))
        st.stop()


storage_call(init_db)
storage = storage_call(storage_status)
if not storage["persistent"]:
    st.warning(
        "Local storage only: hosted Streamlit restarts can erase this data. "
        "Connect a cloud database using the "
        "[setup guide](https://github.com/Shaurya-S0603/Budget-Tracker#persistent-storage-on-streamlit-cloud). "
        "Download a full backup from Weekly Update before changing storage."
    )
if notice := st.session_state.pop("save_notice", None):
    st.success(notice)


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}S${abs(value):,.2f}"


def kpi(label: str, value: str, hint: str = "", state: str = "") -> None:
    st.markdown(
        f'<div class="kpi {state}"><div class="label">{label}</div>'
        f'<div class="value">{value}</div><div class="hint">{hint}</div></div>',
        unsafe_allow_html=True,
    )


def month_rows(df: pd.DataFrame, target: date) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    dated = (
        df["date"].notna()
        & (df["date"].dt.year == target.year)
        & (df["date"].dt.month == target.month)
    )
    legacy = pd.Series(False, index=df.index)
    today = date.today()
    if (target.year, target.month) == (today.year, today.month):
        legacy = df["date"].isna() & (df["entry_mode"] == "legacy")
    return df[dated | legacy].copy()


def emergency_reasons_for_current_month(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    key = date.today().strftime("%Y-%m")
    return df[df["expense_date"].astype(str).str.startswith(key)].copy()


with st.sidebar:
    st.markdown("## 💸 Expense Tracker")
    st.caption("Weekly category totals.")
    page = st.radio(
        "Navigation",
        ["Dashboard", "Weekly Update", "Budgets", "Insights"],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown(f"**Main fund:** {money(MAIN_FUND_LIMIT)}")
    st.markdown(f"**Emergency reserve:** {money(EMERGENCY_FUND_LIMIT)}")
    st.caption("SGD")
    st.caption(str(storage["label"]))

all_expenses = storage_call(get_expenses)
cycle = current_cycle_expenses(all_expenses)
budgets = storage_call(get_budgets)
emergency_uses = storage_call(get_emergency_uses)
total_spent = float(cycle["amount"].sum()) if not cycle.empty else 0.0
fund = fund_status(total_spent)

if page == "Dashboard":
    st.title("Expense Dashboard")
    st.caption(
        ""
    )

    days_total, elapsed_days, remaining_days = month_days()
    daily = total_spent / max(elapsed_days, 1)
    safe_daily = fund["main_remaining"] / max(remaining_days, 1)
    projected = daily * days_total
    projected_fund = fund_status(projected)

    a, b, c, d = st.columns(4)
    with a:
        kpi(
            "Spent this month",
            money(total_spent),
            f"{fund['main_utilization']:.1f}% of main fund",
            "bad" if total_spent > MAIN_FUND_LIMIT else "",
        )
    with b:
        kpi(
            "Main fund left",
            money(fund["main_remaining"]),
            f"of {money(MAIN_FUND_LIMIT)}",
            "good" if fund["main_remaining"] > 0 else "bad",
        )
    with c:
        state = "warn" if fund["emergency_used"] else "good"
        if fund["emergency_used"] >= EMERGENCY_FUND_LIMIT:
            state = "bad"
        kpi(
            "Emergency used",
            money(fund["emergency_used"]),
            f"{money(fund['emergency_remaining'])} left",
            state,
        )
    with d:
        kpi(
            "Safe / day",
            money(safe_daily),
            f"{remaining_days} days left",
            "good" if fund["main_remaining"] > 0 else "bad",
        )

    st.markdown("### Main fund")
    st.progress(
        min(fund["main_utilization"] / 100, 1.0),
        text=f"{money(fund['main_used'])} / {money(MAIN_FUND_LIMIT)}",
    )

    if fund["over_total_funds"] > 0:
        st.error(
            f"Spending is {money(fund['over_total_funds'])} above the full S$1,000 available."
        )
    elif fund["emergency_used"] > 0:
        st.warning(
            f"Main fund exhausted. {money(fund['emergency_used'])} is being covered "
            f"by the Emergency Fund."
        )
    elif fund["main_utilization"] >= 90:
        st.warning(f"Only {money(fund['main_remaining'])} remains in the main fund.")
    else:
        st.success(f"{money(fund['main_remaining'])} remains in the main fund.")

    x, y = st.columns(2)
    with x:
        st.metric(
            "Projected month spend",
            money(projected),
            (
                f"{money(projected - MAIN_FUND_LIMIT)} beyond main fund"
                if projected > MAIN_FUND_LIMIT
                else f"{money(MAIN_FUND_LIMIT - projected)} below main fund"
            ),
        )
    with y:
        st.metric(
            "Projected emergency use",
            money(projected_fund["emergency_used"]),
            "reserve touched" if projected_fund["emergency_used"] else "reserve untouched",
        )

    reasons = emergency_reasons_for_current_month(emergency_uses)
    if fund["emergency_used"] > 0:
        st.markdown("### Why the Emergency Fund was used")
        if reasons.empty:
            st.error(
                "No reason is recorded. Re-save the weekly update that pushed the "
                "month above S$800."
            )
        else:
            st.dataframe(
                reasons[["period_key", "reason"]].rename(
                    columns={"period_key": "Week", "reason": "Reason"}
                ),
                hide_index=True,
                use_container_width=True,
            )

    left, right = st.columns([1.1, 0.9])
    with left:
        st.markdown("### Spending by category")
        if cycle.empty:
            st.info("No spending yet.")
        else:
            category = (
                cycle.groupby("category", as_index=False)["amount"]
                .sum()
                .sort_values("amount")
            )
            fig = px.bar(
                category,
                x="amount",
                y="category",
                orientation="h",
                labels={"amount": "Spent (S$)", "category": ""},
            )
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=350,
                margin=dict(l=0, r=0, t=0, b=0),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("### Category budgets")
        spent_by_cat = (
            cycle.groupby("category")["amount"].sum().to_dict()
            if not cycle.empty
            else {}
        )
        for category, budget in sorted(
            budgets.items(), key=lambda item: item[1], reverse=True
        ):
            spent = float(spent_by_cat.get(category, 0.0))
            ratio = spent / budget if budget else 0.0
            st.markdown(f"**{category}** · {money(spent)} / {money(budget)}")
            st.progress(min(ratio, 1.0), text=f"{ratio * 100:.0f}%")

    st.markdown("### Weekly spending")
    if not cycle.empty:
        weekly = cycle.copy()
        weekly["week"] = weekly.apply(week_label, axis=1)
        weekly = weekly.groupby("week", as_index=False)["amount"].sum()
        fig = px.bar(weekly, x="week", y="amount", labels={"week": "", "amount": "S$"})
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=280,
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

elif page == "Weekly Update":
    st.title("Weekly Spending Update")
    st.caption(
        "Enter one total per category. Re-saving the same week replaces the old values."
    )

    categories = sorted(budgets)
    if not categories:
        st.warning("Add budget categories first.")
    else:
        week_ending = st.date_input("Week ending", value=date.today())
        iso = week_ending.isocalendar()
        period_key = f"{iso.year}-W{iso.week:02d}"

        existing = (
            all_expenses[
                (all_expenses["entry_mode"] == "weekly")
                & (all_expenses["period_key"] == period_key)
            ]
            if not all_expenses.empty
            else pd.DataFrame()
        )
        previous = (
            existing.groupby("category")["amount"].sum().to_dict()
            if not existing.empty
            else {}
        )
        if previous:
            st.info(f"{period_key} already has data. Saving replaces it.")

        st.markdown(f"### {period_key}")
        amounts: dict[str, float] = {}
        for category in categories:
            c1, c2, c3 = st.columns([1.8, 1, 1])
            with c1:
                st.markdown(f"**{category}**")
            with c2:
                st.caption(f"Budget {money(budgets[category])}")
            with c3:
                amounts[category] = st.number_input(
                    f"{category} spent",
                    min_value=0.0,
                    value=float(previous.get(category, 0.0)),
                    step=1.0,
                    format="%.2f",
                    label_visibility="collapsed",
                    key=f"{period_key}_{category}",
                )

        weekly_total = sum(amounts.values())
        relevant = month_rows(all_expenses, week_ending)
        if not relevant.empty:
            replace_mask = (
                (relevant["entry_mode"] == "weekly")
                & (relevant["period_key"] == period_key)
            )
            month_before_this_week = float(relevant.loc[~replace_mask, "amount"].sum())
        else:
            month_before_this_week = 0.0

        prospective_total = month_before_this_week + weekly_total
        preview = fund_status(prospective_total)

        st.markdown(f"**Week total:** {money(weekly_total)}")
        st.caption(f"Month total after save: {money(prospective_total)}")

        old_reason_rows = (
            emergency_uses[emergency_uses["period_key"] == period_key]
            if not emergency_uses.empty
            else pd.DataFrame()
        )
        old_reason = (
            str(old_reason_rows.iloc[0]["reason"]) if not old_reason_rows.empty else ""
        )

        emergency_reason = ""
        if preview["emergency_used"] > 0:
            st.warning(
                f"This leaves the month {money(max(prospective_total - MAIN_FUND_LIMIT, 0))} "
                f"above the S$800 main fund. {money(preview['emergency_used'])} "
                f"will be funded from the Emergency Fund."
            )
            emergency_reason = st.text_area(
                "Why are you using the Emergency Fund?",
                value=old_reason,
                placeholder="Unexpected medical cost, urgent replacement, unavoidable travel...",
            )
            if preview["over_total_funds"] > 0:
                st.error(
                    f"This also exceeds the full S$1,000 available by "
                    f"{money(preview['over_total_funds'])}."
                )

        if st.button("Save weekly spending", type="primary", use_container_width=True):
            if preview["emergency_used"] > 0 and not emergency_reason.strip():
                st.error("Enter a reason before using the Emergency Fund.")
            else:
                try:
                    result = storage_call(
                        upsert_weekly_expenses,
                        week_ending,
                        amounts,
                        emergency_reason=emergency_reason,
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    message = (
                        f"Saved {result['period_key']} · {money(result['weekly_total'])}."
                    )
                    if result["emergency_used"] > 0:
                        message += (
                            f" Emergency Fund currently covering "
                            f"{money(result['emergency_used'])}."
                        )
                    st.session_state["save_notice"] = message
                    st.rerun()

    st.divider()
    st.markdown("### Recorded weeks")
    history = storage_call(get_weekly_totals)
    if history.empty:
        st.caption("No weekly updates yet.")
    else:
        st.dataframe(
            history.rename(
                columns={
                    "period_key": "Week",
                    "week_ending": "Recorded Date",
                    "total_spent": "Total Spent",
                    "categories_recorded": "Categories",
                    "emergency_reason": "Emergency Reason",
                }
            ),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Total Spent": st.column_config.NumberColumn(format="S$ %.2f")
            },
        )
        with st.expander("Delete a week"):
            key = st.selectbox("Week", history["period_key"].tolist())
            if st.button("Delete selected week"):
                storage_call(delete_week, key)
                st.rerun()

    st.divider()
    st.markdown("### Data tools")
    d1, d2 = st.columns(2)
    with d1:
        cols = [
            "expense_date",
            "period_key",
            "category",
            "amount",
            "entry_mode",
            "description",
        ]
        export = (
            all_expenses[cols].copy()
            if not all_expenses.empty
            else pd.DataFrame(columns=cols)
        )
        if not export.empty and not emergency_uses.empty:
            reason_map = emergency_uses.set_index("period_key")["reason"]
            export["emergency_reason"] = export["period_key"].map(reason_map).fillna("")
        else:
            export["emergency_reason"] = ""
        st.download_button(
            "Download spending CSV",
            export.to_csv(index=False).encode("utf-8"),
            "spending_history.csv",
            "text/csv",
            use_container_width=True,
        )

    with d2:
        uploaded = st.file_uploader("Re-import workbook", type=["xlsx"])
        if uploaded is not None:
            replace = st.checkbox("Replace existing spending first")
            if st.button("Import workbook", use_container_width=True):
                try:
                    result = storage_call(import_workbook, BytesIO(uploaded.getvalue()), replace=replace)
                except (ValueError, OSError):
                    st.error("Choose a valid budget workbook with a Transactions sheet.")
                else:
                    st.session_state["save_notice"] = f"Imported {result['expenses_imported']} expense rows."
                    st.rerun()

    with st.expander("Full backup and restore"):
        st.caption("Includes all spending, category budgets and emergency-fund reasons.")
        st.download_button(
            "Download full backup",
            storage_call(export_backup),
            "budget_backup.json",
            "application/json",
            use_container_width=True,
        )
        backup = st.file_uploader("Restore a full backup", type=["json"])
        replace_backup = st.checkbox("Replace all saved data with this backup")
        if st.button("Restore backup", disabled=backup is None):
            try:
                result = storage_call(restore_backup, backup.getvalue(), replace=replace_backup)
            except ValueError as exc:
                st.error(str(exc))
            else:
                # Refill weekly inputs from the newly restored records.
                for key in list(st.session_state):
                    if isinstance(key, str) and len(key) > 8 and key[4:6] == "-W":
                        del st.session_state[key]
                st.session_state["save_notice"] = f"Restored {result['expenses']} expenses and their settings."
                st.rerun()

elif page == "Budgets":
    st.title("Budgets")
    st.caption(
        "Category allocations are inside the fixed S$800 main fund. "
        "Emergency Fund is separate."
    )

    allocated = sum(budgets.values())
    a, b = st.columns(2)
    with a:
        st.metric("Main monthly fund", money(MAIN_FUND_LIMIT), "fixed")
    with b:
        st.metric(
            "Category allocations",
            money(allocated),
            (
                "fully allocated"
                if allocated == MAIN_FUND_LIMIT
                else f"{money(abs(MAIN_FUND_LIMIT - allocated))} "
                f"{'over' if allocated > MAIN_FUND_LIMIT else 'unallocated'}"
            ),
        )
    if allocated > MAIN_FUND_LIMIT:
        st.warning("Category allocations exceed S$800. The main fund is still capped at S$800.")

    spent = (
        cycle.groupby("category")["amount"].sum().to_dict()
        if not cycle.empty
        else {}
    )
    rows = []
    for category, budget in sorted(budgets.items()):
        used = float(spent.get(category, 0.0))
        rows.append(
            {
                "Category": category,
                "Monthly Budget": budget,
                "Spent": used,
                "Remaining": budget - used,
                "Used %": used / budget * 100 if budget else 0.0,
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        st.dataframe(
            frame,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Monthly Budget": st.column_config.NumberColumn(format="S$ %.2f"),
                "Spent": st.column_config.NumberColumn(format="S$ %.2f"),
                "Remaining": st.column_config.NumberColumn(format="S$ %.2f"),
                "Used %": st.column_config.ProgressColumn(
                    min_value=0, max_value=100, format="%.0f%%"
                ),
            },
        )

    left, right = st.columns(2)
    with left:
        st.markdown("### Update")
        if budgets:
            category = st.selectbox("Category", sorted(budgets))
            value = st.number_input(
                "Monthly budget",
                min_value=0.0,
                value=float(budgets[category]),
                step=5.0,
            )
            if st.button("Save budget", type="primary", use_container_width=True):
                storage_call(upsert_budget, category, value)
                st.rerun()

    with right:
        st.markdown("### Add category")
        new_category = st.text_input("New category")
        new_budget = st.number_input(
            "Budget",
            min_value=0.0,
            value=0.0,
            step=5.0,
            key="new_budget",
        )
        if st.button("Add category", use_container_width=True):
            if not new_category.strip():
                st.error("Enter a category name.")
            elif new_category.strip().casefold() == "emergency fund":
                st.error("Emergency Fund is a reserve, not an expense category.")
            else:
                storage_call(upsert_budget, new_category.strip(), new_budget)
                st.rerun()

    with st.expander("Delete category"):
        if budgets:
            category = st.selectbox(
                "Category to delete",
                sorted(budgets),
                key="delete_category",
            )
            if st.button("Delete budget category"):
                storage_call(delete_budget, category)
                st.rerun()

elif page == "Insights":
    st.title("Insights")
    if cycle.empty:
        st.info("Record spending to generate insights.")
    else:
        days_total, elapsed_days, _ = month_days()
        projected = total_spent / max(elapsed_days, 1) * days_total
        projected_fund = fund_status(projected)
        top = cycle.groupby("category")["amount"].sum().sort_values(ascending=False)
        weekly_only = cycle[cycle["entry_mode"] == "weekly"]
        weekly_avg = (
            weekly_only.groupby("period_key")["amount"].sum().mean()
            if not weekly_only.empty
            else 0.0
        )

        a, b, c = st.columns(3)
        with a:
            st.metric("Top category", top.index[0], money(float(top.iloc[0])))
        with b:
            st.metric("Average recorded week", money(float(weekly_avg)))
        with c:
            st.metric(
                "Projected emergency use",
                money(projected_fund["emergency_used"]),
            )

        if projected_fund["over_total_funds"] > 0:
            st.error(
                f"At this pace you exceed all S$1,000 by "
                f"{money(projected_fund['over_total_funds'])}."
            )
        elif projected_fund["emergency_used"] > 0:
            st.warning(
                f"At this pace about {money(projected_fund['emergency_used'])} "
                f"of the Emergency Fund will be used."
            )

        st.markdown("### Category warnings")
        spent_by_cat = cycle.groupby("category")["amount"].sum().to_dict()
        warnings = []
        for category, budget in budgets.items():
            if budget <= 0:
                continue
            amount = float(spent_by_cat.get(category, 0.0))
            pct = amount / budget * 100
            if pct > 100:
                warnings.append(
                    (3, f"**{category}:** {pct:.0f}% used, {money(amount - budget)} over.")
                )
            elif pct >= 90:
                warnings.append(
                    (2, f"**{category}:** {pct:.0f}% used, {money(budget - amount)} left.")
                )
            elif pct >= 70:
                warnings.append((1, f"**{category}:** {pct:.0f}% used."))

        if not warnings:
            st.success("No category is above 70% of its budget.")
        for level, message in sorted(warnings, reverse=True):
            (st.error if level == 3 else st.warning)(message)

        reasons = emergency_reasons_for_current_month(emergency_uses)
        if not reasons.empty:
            st.markdown("### Emergency Fund history")
            st.dataframe(
                reasons[["period_key", "reason"]].rename(
                    columns={"period_key": "Week", "reason": "Reason"}
                ),
                hide_index=True,
                use_container_width=True,
            )

        st.markdown("### Spending concentration")
        category = (
            cycle.groupby("category", as_index=False)["amount"]
            .sum()
            .sort_values("amount", ascending=False)
        )
        fig = px.pie(category, names="category", values="amount", hole=0.55)
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=420,
            margin=dict(l=0, r=0, t=0, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
