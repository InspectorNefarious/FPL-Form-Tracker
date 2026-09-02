"""
app.py

Streamlit dashboard for browsing weekly Premier League player form,
sourced from the local fpl_form.db database built by fetch_data.py.

Run with:

    streamlit run app.py

If fpl_form.db doesn't exist yet or looks empty, run `python fetch_data.py`
first (see README.md).
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from fetch_data import refresh_all_data

DB_PATH = Path(__file__).parent / "fpl_form.db"

st.set_page_config(page_title="PL Player Form Tracker", layout="wide")


def run_refresh() -> None:
    """Fetch fresh data from the FPL API, showing progress in the UI."""
    status_box = st.empty()
    lines: list[str] = []

    def on_progress(msg: str) -> None:
        lines.append(msg)
        status_box.code("\n".join(lines[-8:]))

    with st.spinner("Fetching latest data from the FPL API..."):
        try:
            refresh_all_data(DB_PATH, progress_callback=on_progress)
        except Exception as exc:  # noqa: BLE001 - surface any fetch error to the user
            st.error(f"Refresh failed: {exc}")
            return
    st.cache_data.clear()
    st.success("Data refreshed.")


# On Streamlit Community Cloud there's no separate terminal step, so fetch
# automatically the first time the app runs (i.e. the db doesn't exist yet).
if not DB_PATH.exists():
    st.info("First run — fetching current season data from the FPL API...")
    run_refresh()

st.sidebar.header("Data")
if st.sidebar.button("🔄 Refresh data now"):
    run_refresh()
if DB_PATH.exists():
    st.sidebar.caption(f"Last refreshed: {pd.Timestamp.fromtimestamp(DB_PATH.stat().st_mtime):%Y-%m-%d %H:%M}")


@st.cache_data(ttl=300)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = sqlite3.connect(DB_PATH)
    players = pd.read_sql_query(
        """
        SELECT
            p.id AS player_id,
            p.web_name,
            p.first_name,
            p.second_name,
            t.name AS team,
            pos.singular_name AS position,
            p.now_cost / 10.0 AS price,
            p.status
        FROM players p
        JOIN teams t ON t.id = p.team_id
        JOIN positions pos ON pos.id = p.position_id
        """,
        conn,
    )
    stats = pd.read_sql_query(
        """
        SELECT player_id, gameweek_id, total_points, minutes,
               goals_scored, assists, clean_sheets, bonus
        FROM player_gameweek_stats
        ORDER BY gameweek_id
        """,
        conn,
    )
    conn.close()
    return players, stats


players_df, stats_df = load_data()

if stats_df.empty:
    st.warning(
        "No gameweek data found yet. Run `python fetch_data.py` first, "
        "then reload this page."
    )
    st.stop()

gameweeks = sorted(stats_df["gameweek_id"].unique())
merged = stats_df.merge(players_df, on="player_id", how="left")

st.title("Premier League Player Form Tracker")
st.caption(
    f"Data through Gameweek {gameweeks[-1]} · "
    f"{players_df.shape[0]} players tracked"
)

# --- Sidebar filters -------------------------------------------------
st.sidebar.header("Filters")

form_window = st.sidebar.slider(
    "Form window (last N gameweeks)", min_value=1, max_value=len(gameweeks),
    value=min(5, len(gameweeks)),
)

teams = sorted(players_df["team"].unique())
selected_teams = st.sidebar.multiselect("Team", teams, default=[])

positions = sorted(players_df["position"].unique())
selected_positions = st.sidebar.multiselect("Position", positions, default=[])

min_minutes = st.sidebar.number_input(
    "Min total minutes played", min_value=0, value=0, step=90
)

search = st.sidebar.text_input("Search player name")

# --- Compute form table -----------------------------------------------
recent_gws = gameweeks[-form_window:]
recent = merged[merged["gameweek_id"].isin(recent_gws)]

agg = (
    recent.groupby("player_id")
    .agg(
        form_points=("total_points", "sum"),
        form_avg=("total_points", "mean"),
        gws_played=("gameweek_id", "nunique"),
        total_minutes=("minutes", "sum"),
        goals=("goals_scored", "sum"),
        assists=("assists", "sum"),
        bonus=("bonus", "sum"),
    )
    .reset_index()
)

table = agg.merge(players_df, on="player_id", how="left")
table["form_avg"] = table["form_avg"].round(2)

if selected_teams:
    table = table[table["team"].isin(selected_teams)]
if selected_positions:
    table = table[table["position"].isin(selected_positions)]
if min_minutes:
    table = table[table["total_minutes"] >= min_minutes]
if search:
    table = table[table["web_name"].str.contains(search, case=False, na=False)]

table = table.sort_values("form_points", ascending=False)

st.subheader(f"Form over last {form_window} gameweek(s) — GW{recent_gws[0]}\u2013{recent_gws[-1]}")
st.dataframe(
    table[
        [
            "web_name",
            "team",
            "position",
            "price",
            "form_points",
            "form_avg",
            "gws_played",
            "goals",
            "assists",
            "bonus",
            "total_minutes",
        ]
    ].rename(
        columns={
            "web_name": "Player",
            "team": "Team",
            "position": "Position",
            "price": "Price (\u00a3m)",
            "form_points": "Form pts (total)",
            "form_avg": "Form pts (avg/gw)",
            "gws_played": "GWs played",
            "goals": "Goals",
            "assists": "Assists",
            "bonus": "Bonus",
            "total_minutes": "Minutes",
        }
    ),
    use_container_width=True,
    hide_index=True,
    height=500,
)

# --- Player detail / trend chart --------------------------------------
st.subheader("Player gameweek trend")
player_options = table["web_name"] + " (" + table["team"] + ")"
name_to_id = dict(zip(player_options, table["player_id"]))

if len(player_options) == 0:
    st.info("No players match the current filters.")
else:
    chosen = st.selectbox("Pick a player", sorted(player_options))
    pid = name_to_id[chosen]
    player_history = merged[merged["player_id"] == pid].sort_values("gameweek_id")
    chart_df = player_history.set_index("gameweek_id")[["total_points"]]
    chart_df.index.name = "Gameweek"
    chart_df.columns = ["Points"]
    st.line_chart(chart_df)
    st.dataframe(
        player_history[
            ["gameweek_id", "total_points", "minutes", "goals_scored", "assists", "bonus"]
        ].rename(
            columns={
                "gameweek_id": "GW",
                "total_points": "Points",
                "minutes": "Minutes",
                "goals_scored": "Goals",
                "assists": "Assists",
                "bonus": "Bonus",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
