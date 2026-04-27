"""Claude Analytics Dashboard — multi-app revenue & experiment tracker."""
import os
import json
from datetime import date, datetime, timedelta

import pandas as pd
import psycopg2
import streamlit as st

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Claude Analytics",
    layout="wide",
    page_icon="📊",
    initial_sidebar_state="expanded",
)

DB_HOST = os.environ.get("DB_HOST", "jo0c0k0kg4g8okko4ks48g8g")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "claude_analytics")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS", "postgres")
DASH_PASSWORD = os.environ.get("DASH_PASSWORD", "")


# ------------------------------------------------------------------
# Auth gate
# ------------------------------------------------------------------
def password_gate() -> bool:
    if not DASH_PASSWORD:
        return True
    if st.session_state.get("authed"):
        return True
    pw = st.text_input("Password", type="password")
    if pw == DASH_PASSWORD:
        st.session_state["authed"] = True
        st.rerun()
    elif pw:
        st.error("Wrong password")
    return False


if not password_gate():
    st.stop()


# ------------------------------------------------------------------
# DB
# ------------------------------------------------------------------
@st.cache_resource
def get_conn():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql(sql, get_conn(), params=params)


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
apps = q("SELECT id, name FROM apps ORDER BY name")
if apps.empty:
    st.error("No apps configured in the database.")
    st.stop()

with st.sidebar:
    st.title("📊 Claude Analytics")
    app_choice = st.selectbox(
        "App",
        apps["id"],
        format_func=lambda i: apps.loc[apps["id"] == i, "name"].iloc[0],
    )
    st.caption(f"DB: `{DB_NAME}` · {len(apps)} app(s)")
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()

app_name = apps.loc[apps["id"] == app_choice, "name"].iloc[0]
st.title(app_name)


# ------------------------------------------------------------------
# Top: due-for-recheck across ALL apps
# ------------------------------------------------------------------
st.subheader("⏰ Due for recheck (all apps)")
due = q(
    """
    SELECT a.name AS app, ai.id, ai.recheck_date, ai.title,
           ai.completed_at::date AS shipped, ai.priority
    FROM action_items ai
    JOIN apps a ON a.id = ai.app_id
    WHERE ai.status = 'done'
      AND ai.outcome IS NULL
      AND ai.recheck_date IS NOT NULL
      AND ai.recheck_date <= CURRENT_DATE + INTERVAL '7 days'
    ORDER BY ai.recheck_date
    """
)
if due.empty:
    st.success("Nothing due for recheck in the next 7 days.")
else:
    today = date.today()
    due["overdue"] = due["recheck_date"].apply(
        lambda d: "🔴" if d < today else ("🟡" if d <= today + timedelta(days=2) else "⚪")
    )
    st.dataframe(due[["overdue", "app", "recheck_date", "title", "shipped"]],
                 use_container_width=True, hide_index=True)


# ------------------------------------------------------------------
# Tabs for selected app
# ------------------------------------------------------------------
t_kpis, t_actions, t_snapshots, t_insights = st.tabs(
    ["📈 KPIs", "📋 Action items", "📸 Snapshots", "💡 Insights"]
)


# --- KPIs --------------------------------------------------------
with t_kpis:
    kpis = q(
        """
        SELECT id, measurement_date, kpi_name, value, unit, window_days,
               source, notes
        FROM kpi_measurements
        WHERE app_id = %s
        ORDER BY measurement_date DESC, kpi_name
        """,
        (int(app_choice),),
    )

    if kpis.empty:
        st.info("No KPI measurements yet for this app.")
    else:
        # ----- LATEST values per KPI ----------------------------
        st.markdown("### Latest values")
        latest = (
            kpis.sort_values("measurement_date", ascending=False)
                .drop_duplicates("kpi_name")
                .sort_values("kpi_name")
        )

        # 4-column grid of metrics
        rows = [latest.iloc[i:i+4] for i in range(0, len(latest), 4)]
        for chunk in rows:
            cols = st.columns(4)
            for col, (_, r) in zip(cols, chunk.iterrows()):
                unit = r["unit"] or ""
                if unit == "USD":
                    val = f"${float(r['value']):,.0f}"
                elif unit == "pct":
                    val = f"{float(r['value']):.1f}%"
                elif unit == "count":
                    val = f"{float(r['value']):,.0f}"
                else:
                    val = f"{r['value']}"
                col.metric(r["kpi_name"], val, help=r["notes"])

        # ----- BEFORE / AFTER comparison ------------------------
        st.markdown("### Before / After (per shipped action item)")
        shipped = q(
            """
            SELECT id, title, completed_at::date AS shipped_on,
                   recheck_date
            FROM action_items
            WHERE app_id = %s AND status = 'done' AND completed_at IS NOT NULL
            ORDER BY completed_at DESC
            """,
            (int(app_choice),),
        )
        if shipped.empty:
            st.caption("No shipped action items yet.")
        else:
            for _, item in shipped.iterrows():
                ship_date = item["shipped_on"]
                with st.expander(
                    f"#{item['id']} — {item['title']}  "
                    f"(shipped {ship_date} · recheck {item['recheck_date'] or '—'})"
                ):
                    # Baseline = latest measurement on or BEFORE ship_date
                    baseline = (
                        kpis[kpis["measurement_date"] <= ship_date]
                        .sort_values("measurement_date", ascending=False)
                        .drop_duplicates("kpi_name")
                        [["kpi_name", "measurement_date", "value", "unit"]]
                        .rename(columns={"measurement_date": "baseline_date",
                                         "value": "baseline_value"})
                    )
                    # Current = latest measurement AFTER ship_date
                    after = (
                        kpis[kpis["measurement_date"] > ship_date]
                        .sort_values("measurement_date", ascending=False)
                        .drop_duplicates("kpi_name")
                        [["kpi_name", "measurement_date", "value"]]
                        .rename(columns={"measurement_date": "current_date",
                                         "value": "current_value"})
                    )
                    cmp = baseline.merge(after, on="kpi_name", how="left")
                    if cmp.empty:
                        st.caption("No baseline KPIs locked in before this ship date.")
                        continue
                    cmp["delta"] = cmp["current_value"] - cmp["baseline_value"]
                    cmp["pct_change"] = (cmp["delta"] / cmp["baseline_value"] * 100).round(1)
                    if cmp["current_value"].isna().all():
                        st.caption(
                            f"⏳ No post-ship measurements yet. Recheck on "
                            f"**{item['recheck_date']}** — pull fresh KPIs and INSERT into "
                            f"`kpi_measurements` to populate this comparison."
                        )
                    st.dataframe(
                        cmp[["kpi_name", "unit", "baseline_value", "baseline_date",
                             "current_value", "current_date", "delta", "pct_change"]],
                        use_container_width=True, hide_index=True,
                    )

        # ----- Per-KPI history (line chart) ---------------------
        st.markdown("### KPI history")
        kpi_pick = st.selectbox(
            "Pick a KPI",
            sorted(kpis["kpi_name"].unique()),
        )
        if kpi_pick:
            series = (
                kpis[kpis["kpi_name"] == kpi_pick]
                .sort_values("measurement_date")
                [["measurement_date", "value"]]
                .set_index("measurement_date")
            )
            if len(series) >= 2:
                st.line_chart(series, height=240)
            else:
                st.info(
                    f"Only 1 measurement for `{kpi_pick}` so far. "
                    f"Chart appears once you have ≥2 measurements."
                )
            st.caption("Raw measurements:")
            st.dataframe(
                kpis[kpis["kpi_name"] == kpi_pick]
                    [["measurement_date", "value", "unit", "window_days", "source", "notes"]],
                use_container_width=True, hide_index=True,
            )

# --- Action items --------------------------------------------------
with t_actions:
    items = q(
        """
        SELECT id, priority, status, title, recheck_date,
               completed_at::date AS shipped_on,
               (outcome IS NOT NULL) AS reviewed,
               outcome
        FROM action_items
        WHERE app_id = %s
        ORDER BY status, priority, id
        """,
        (int(app_choice),),
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pending", int((items["status"] == "pending").sum()))
    col2.metric("Done (waiting recheck)", int(((items["status"] == "done") & (~items["reviewed"])).sum()))
    col3.metric("Reviewed", int(items["reviewed"].sum()))
    col4.metric("Total", len(items))

    st.dataframe(items, use_container_width=True, hide_index=True)

    # Inspect single item
    pick = st.selectbox(
        "Inspect action item",
        items["id"],
        format_func=lambda i: f"#{i} — {items.loc[items['id']==i,'title'].iloc[0][:60]}",
    )
    if pick:
        row = q("SELECT * FROM action_items WHERE id = %s", (int(pick),)).iloc[0]
        with st.expander("Details", expanded=True):
            st.write(f"**Title:** {row['title']}")
            st.write(f"**Status:** `{row['status']}` · **Priority:** {row['priority']} · **Recheck:** {row['recheck_date']}")
            if row["detail"]:
                st.markdown("**Detail**")
                st.write(row["detail"])
            if row["outcome_data"]:
                st.markdown("**Outcome data**")
                st.json(row["outcome_data"])
            if row["outcome"]:
                st.markdown("**Outcome**")
                st.write(row["outcome"])

# --- Funnel snapshots ---------------------------------------------
with t_snapshots:
    snaps = q(
        """
        SELECT id, snapshot_date, funnel_name, notes
        FROM funnel_snapshots
        WHERE app_id = %s
        ORDER BY snapshot_date DESC, funnel_name
        """,
        (int(app_choice),),
    )
    if snaps.empty:
        st.info("No snapshots yet for this app.")
    else:
        st.dataframe(snaps, use_container_width=True, hide_index=True)
        pick_s = st.selectbox(
            "Inspect snapshot",
            snaps["id"],
            format_func=lambda i: f"#{i} · {snaps.loc[snaps['id']==i,'snapshot_date'].iloc[0]} · {snaps.loc[snaps['id']==i,'funnel_name'].iloc[0]}",
        )
        if pick_s:
            data = q("SELECT steps, notes FROM funnel_snapshots WHERE id = %s", (int(pick_s),)).iloc[0]
            if data["notes"]:
                st.caption(data["notes"])
            st.json(data["steps"])

# --- Insights -----------------------------------------------------
with t_insights:
    ins = q(
        """
        SELECT id, session_date, category, title, detail
        FROM insights
        WHERE app_id = %s
        ORDER BY session_date DESC, id DESC
        """,
        (int(app_choice),),
    )
    if ins.empty:
        st.info("No insights yet for this app.")
    else:
        st.dataframe(ins, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------
# Footer
# ------------------------------------------------------------------
st.caption(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
           f"`{app_name}` · {len(apps)} apps in DB")
