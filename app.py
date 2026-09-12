from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from db import (
    current_cycle_expenses,
    delete_budget,
    delete_week,
    get_budgets,
    get_expenses,
    get_weekly_totals,
    import_workbook,
    init_db,
    month_days,
    upsert_budget,
    upsert_weekly_expenses,
    week_label,
)

st.set_page_config(
    page_title="Student Expense Tracker",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
:root {
  --bg: #090c10;
  --panel: #11161d;
  --border: #27313d;
  --text: #f3f6f9;
  --muted: #8d99a6;
  --green: #39d98a;
  --amber: #f4b860;
  --red: #ff6b6b;
}
.stApp { background: var(--bg); color: var(--text); }
[data-testid="stSidebar"] { background: #0d1117; border-right: 1px solid var(--border); }
[data-testid="stHeader"] { background: rgba(9,12,16,.85); }
.block-container { padding-top: 1.5rem; max-width: 1450px; }
h1, h2, h3 { letter-spacing: -0.02em; }
.kpi {
  background: linear-gradient(180deg, #141a22 0%, #10151c 100%);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 18px 20px;
  min-height: 120px;
  box-shadow: 0 8px 24px rgba(0,0,0,.22);
}
.kpi .label { color: var(--muted); font-size: .8rem; font-weight: 650; text-transform: uppercase; letter-spacing: .07em; }
.kpi .value { color: var(--text); font-size: 2rem; font-weight: 800; margin-top: 7px; }
.kpi .hint { color: var(--muted); font-size: .78rem; margin-top: 5px; }
.kpi.good .value { color: var(--green); }
.kpi.warn .value { color: var(--amber); }
.kpi.bad .value { color: var(--red); }
[data-testid="stMetric"] { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 14px 16px; }
.stButton > button, .stDownloadButton > button { border-radius: 10px; border: 1px solid #33404e; font-weight: 700; }
.stButton > button[kind="primary"] { background: #2cb67d; color: #04120d; border: none; }
div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, textarea { background-color: #11161d !important; border-color: #2a3440 !important; }
[data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
hr { border-color: var(--border); }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

init_db()


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}S${abs(value):,.2f}"


def kpi_card(label: str, value: str, hint: str = "", state: str = "") -> None:
    st.markdown(
        f"""
        <div class="kpi {state}">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
            <div class="hint">{hint}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def load_data():
    all_expenses = get_expenses()
    cycle = current_cycle_expenses(all_expenses)
    budgets = get_budgets()
    return all_expenses, cycle, budgets


def budget_summary(cycle: pd.DataFrame, budgets: dict[str, float]):
    total_budget = sum(budgets.values())
    total_spent = float(cycle["amount"].sum()) if not cycle.empty else 0.0
    remaining = total_budget - total_spent
    utilization = (total_spent / total_budget * 100) if total_budget else 0.0
    return total_budget, total_spent, remaining, utilization


with st.sidebar:
    st.markdown("## 💸 Expense Tracker")
    st.caption("Weekly category totals. No receipt archaeology required.")
    page = st.radio(
        "Navigation",
        ["Dashboard", "Weekly Update", "Budgets", "Insights"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Currency")
    st.markdown("**SGD (S$)**")

all_expenses, cycle, budgets = load_data()
total_budget, total_spent, remaining, utilization = budget_summary(cycle, budgets)

if page == "Dashboard":
    st.title("Expense Dashboard")
    st.caption("Current month plus the undated starting expenses imported from your original workbook.")

    days_total, elapsed_days, remaining_days = month_days()
    avg_daily = total_spent / max(elapsed_days, 1)
    safe_daily = max(remaining, 0) / max(remaining_days, 1)
    projected = avg_daily * days_total

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card("Spent this month", money(total_spent), f"{utilization:.1f}% of budget", "bad" if utilization > 100 else "")
    with c2:
        kpi_card("Budget left", money(remaining), f"of {money(total_budget)}", "good" if remaining >= 0 else "bad")
    with c3:
        kpi_card("Safe to spend / day", money(safe_daily), f"{remaining_days} days left", "good" if remaining >= 0 else "bad")
    with c4:
        state = "bad" if projected > total_budget else "warn" if projected > total_budget * .9 else "good"
        kpi_card("Projected month spend", money(projected), "based on current pace", state)

    st.markdown("### Budget pace")
    st.progress(min(max(utilization / 100, 0.0), 1.0), text=f"{utilization:.1f}% used · {money(total_spent)} of {money(total_budget)}")
    if utilization > 100:
        st.error(f"You are {money(abs(remaining))} over the monthly budget.")
    elif utilization > 90:
        st.warning(f"Only {money(remaining)} remains this month.")
    elif utilization > 70:
        st.warning(f"You have used {utilization:.0f}% of the monthly budget.")
    else:
        st.success(f"You still have {money(remaining)} available this month.")

    left, right = st.columns([1.12, .88])
    with left:
        st.markdown("### Where the money went")
        if cycle.empty:
            st.info("No spending recorded yet.")
        else:
            cat = cycle.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=True)
            fig = px.bar(cat, x="amount", y="category", orientation="h", text_auto=".2s", labels={"amount": "Spent (S$)", "category": ""})
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=10, t=10, b=0), height=360, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("### Category budget status")
        spent_by_cat = cycle.groupby("category")["amount"].sum().to_dict() if not cycle.empty else {}
        for category, budget in sorted(budgets.items(), key=lambda x: x[1], reverse=True):
            spent = float(spent_by_cat.get(category, 0.0))
            used = spent / budget if budget else 0.0
            st.markdown(f"**{category}** · {money(spent)} / {money(budget)}")
            st.progress(min(max(used, 0.0), 1.0), text=f"{used*100:.0f}%")

    st.markdown("### Weekly spending")
    if cycle.empty:
        st.info("No weekly data yet.")
    else:
        wk = cycle.copy()
        wk["week"] = wk.apply(week_label, axis=1)
        weekly = wk.groupby("week", as_index=False)["amount"].sum()
        fig = px.bar(weekly, x="week", y="amount", text_auto=".2s", labels={"week": "", "amount": "Spent (S$)"})
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=10, t=10, b=0), height=300, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

elif page == "Weekly Update":
    st.title("Weekly Spending Update")
    st.caption("At the end of each week, enter the total amount spent in each category. Re-saving the same week replaces it rather than adding duplicates.")

    categories = sorted(budgets.keys())
    if not categories:
        st.warning("Add budget categories first.")
    else:
        week_ending = st.date_input("Week ending", value=date.today(), help="Any date in the week works; the app stores it under the matching ISO week.")

        existing_week_key = f"{week_ending.isocalendar().year}-W{week_ending.isocalendar().week:02d}"
        existing = all_expenses[
            (all_expenses["entry_mode"] == "weekly")
            & (all_expenses["period_key"] == existing_week_key)
        ] if not all_expenses.empty else pd.DataFrame()
        previous = existing.groupby("category")["amount"].sum().to_dict() if not existing.empty else {}

        if previous:
            st.info(f"{existing_week_key} already has data. Saving below will replace that week's totals.")

        with st.form("weekly_update"):
            st.markdown(f"### {existing_week_key}")
            amounts: dict[str, float] = {}
            for category in categories:
                c1, c2, c3 = st.columns([1.8, 1, 1])
                with c1:
                    st.markdown(f"**{category}**")
                with c2:
                    st.caption(f"Monthly budget {money(float(budgets[category]))}")
                with c3:
                    amounts[category] = st.number_input(
                        f"{category} spent",
                        min_value=0.0,
                        value=float(previous.get(category, 0.0)),
                        step=1.0,
                        format="%.2f",
                        label_visibility="collapsed",
                        key=f"weekly_{existing_week_key}_{category}",
                    )
            weekly_total = sum(amounts.values())
            st.markdown(f"**Week total: {money(weekly_total)}**")
            submitted = st.form_submit_button("Save weekly spending", type="primary", use_container_width=True)
            if submitted:
                result = upsert_weekly_expenses(week_ending, amounts)
                st.success(f"Saved {result['categories_saved']} categories for {result['period_key']} · {money(result['total'])} total.")
                st.rerun()

    st.divider()
    st.markdown("### Recorded weeks")
    weekly_history = get_weekly_totals()
    if weekly_history.empty:
        st.caption("No weekly updates recorded yet.")
    else:
        display = weekly_history.rename(columns={
            "period_key": "Week",
            "week_ending": "Recorded Date",
            "total_spent": "Total Spent",
            "categories_recorded": "Categories",
        })
        st.dataframe(
            display,
            hide_index=True,
            use_container_width=True,
            column_config={"Total Spent": st.column_config.NumberColumn(format="S$ %.2f")},
        )
        with st.expander("Delete a recorded week"):
            delete_key = st.selectbox("Week", weekly_history["period_key"].tolist())
            if st.button("Delete week", use_container_width=True):
                delete_week(delete_key)
                st.success(f"Deleted {delete_key}.")
                st.rerun()

    st.divider()
    st.markdown("### Data tools")
    d1, d2 = st.columns(2)
    with d1:
        export_cols = ["expense_date", "period_key", "category", "amount", "entry_mode", "description"]
        export_df = all_expenses[export_cols].copy() if not all_expenses.empty else pd.DataFrame(columns=export_cols)
        st.download_button("Download spending CSV", data=export_df.to_csv(index=False).encode("utf-8"), file_name="spending_history.csv", mime="text/csv", use_container_width=True)
    with d2:
        uploaded = st.file_uploader("Re-import original-format Excel workbook", type=["xlsx"])
        if uploaded is not None:
            temp_path = Path("data") / "uploaded_budget.xlsx"
            temp_path.write_bytes(uploaded.getbuffer())
            replace = st.checkbox("Replace all existing spending first", value=False)
            if st.button("Import workbook", use_container_width=True):
                result = import_workbook(temp_path, replace=replace)
                st.success(f"Imported {result['expenses_imported']} expenses and {result['budget_categories_imported']} budget categories.")
                st.rerun()

elif page == "Budgets":
    st.title("Budgets")
    st.caption("Monthly category limits. The total monthly budget is the sum of these categories.")

    spent_by_cat = cycle.groupby("category")["amount"].sum().to_dict() if not cycle.empty else {}
    rows = []
    for category, budget in sorted(budgets.items()):
        spent = float(spent_by_cat.get(category, 0.0))
        rows.append({
            "Category": category,
            "Monthly Budget": budget,
            "Spent": spent,
            "Remaining": budget - spent,
            "Used %": (spent / budget * 100) if budget else 0.0,
        })
    budget_df = pd.DataFrame(rows)

    if not budget_df.empty:
        st.dataframe(
            budget_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Monthly Budget": st.column_config.NumberColumn(format="S$ %.2f"),
                "Spent": st.column_config.NumberColumn(format="S$ %.2f"),
                "Remaining": st.column_config.NumberColumn(format="S$ %.2f"),
                "Used %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
            },
        )

    b1, b2 = st.columns(2)
    with b1:
        st.markdown("### Update a budget")
        if budgets:
            cat = st.selectbox("Category", sorted(budgets.keys()), key="budget_cat")
            value = st.number_input("Monthly budget (S$)", min_value=0.0, value=float(budgets[cat]), step=5.0)
            if st.button("Save budget", type="primary", use_container_width=True):
                upsert_budget(cat, value)
                st.success("Budget updated.")
                st.rerun()
    with b2:
        st.markdown("### Add a category")
        new_cat = st.text_input("New category")
        new_budget = st.number_input("Budget (S$)", min_value=0.0, value=0.0, step=5.0, key="new_budget")
        if st.button("Add category", use_container_width=True):
            if not new_cat.strip():
                st.error("Enter a category name.")
            else:
                upsert_budget(new_cat.strip(), new_budget)
                st.success("Category added.")
                st.rerun()

    st.markdown("### Category pace")
    if not budget_df.empty:
        for _, r in budget_df.sort_values("Used %", ascending=False).iterrows():
            used = float(r["Used %"])
            label = f"{r['Category']} · {used:.0f}% · {money(float(r['Remaining']))} left"
            st.progress(min(max(used / 100, 0.0), 1.0), text=label)
            if used > 100:
                st.error(f"{r['Category']} is {money(abs(float(r['Remaining'])))} over budget.")

    with st.expander("Delete a budget category"):
        if budgets:
            del_cat = st.selectbox("Category to delete", sorted(budgets.keys()), key="delete_budget_cat")
            if st.button("Delete budget category"):
                delete_budget(del_cat)
                st.success("Budget category deleted. Existing spending history is untouched.")
                st.rerun()

elif page == "Insights":
    st.title("Insights")
    st.caption("Useful spending signals without turning your groceries into a quarterly earnings call.")

    if cycle.empty:
        st.info("Record spending to generate insights.")
    else:
        days_total, elapsed_days, _ = month_days()
        avg_daily = total_spent / max(elapsed_days, 1)
        projected = avg_daily * days_total
        top = cycle.groupby("category")["amount"].sum().sort_values(ascending=False)
        top_cat = top.index[0]
        top_amt = float(top.iloc[0])

        i1, i2, i3 = st.columns(3)
        with i1:
            st.metric("Top category", top_cat, money(top_amt))
        with i2:
            weekly_only = cycle[cycle["entry_mode"] == "weekly"]
            weekly_avg = weekly_only.groupby("period_key")["amount"].sum().mean() if not weekly_only.empty else 0.0
            st.metric("Average recorded week", money(float(weekly_avg)))
        with i3:
            delta = projected - total_budget
            st.metric("Projected month spend", money(projected), f"{money(abs(delta))} {'over' if delta > 0 else 'under'} budget")

        st.markdown("### What needs attention")
        spent_by_cat = cycle.groupby("category")["amount"].sum().to_dict()
        messages = []
        for category, budget in budgets.items():
            spent = float(spent_by_cat.get(category, 0.0))
            if budget <= 0:
                continue
            pct = spent / budget * 100
            if pct > 100:
                messages.append((3, f"**{category}:** {pct:.0f}% used, {money(spent - budget)} over budget."))
            elif pct >= 90:
                messages.append((2, f"**{category}:** {pct:.0f}% used. Only {money(budget - spent)} remains."))
            elif pct >= 70:
                messages.append((1, f"**{category}:** {pct:.0f}% used. Keep an eye on it."))

        if not messages:
            st.success("No category is above 70% of its monthly budget yet.")
        else:
            for level, msg in sorted(messages, reverse=True):
                if level == 3:
                    st.error(msg)
                else:
                    st.warning(msg)

        st.markdown("### Spending concentration")
        cat = cycle.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
        fig = px.pie(cat, names="category", values="amount", hole=.55)
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=10, b=0), height=430, legend_title_text="")
        st.plotly_chart(fig, use_container_width=True)

        legacy_count = int(((cycle["entry_mode"] == "legacy") & cycle["date"].isna()).sum())
        if legacy_count:
            st.info(f"{legacy_count} starting expense row(s) from the workbook have no date. They count toward this month's starting budget, while new updates are tracked by week.")
