"""
fetch_data.py

Pulls player and gameweek data from the official (undocumented) Fantasy
Premier League API and stores it in a local SQLite database so it can be
tracked over time.

Run this once a week (or any time) to refresh the data:

    python fetch_data.py

It is safe to re-run — each run replaces the gameweek/player snapshot
tables with the latest data from the API, so the database always reflects
the current state of the season. Nothing is "lost" between runs because
FPL's API keeps the full gameweek-by-gameweek history for the season.

Data source:
  - https://fantasy.premierleague.com/api/bootstrap-static/
      -> players, teams, positions, list of gameweeks ("events")
  - https://fantasy.premierleague.com/api/event/{gw}/live/
      -> every player's stats (incl. points) for a single finished gameweek

Using the per-gameweek "live" endpoint instead of calling
element-summary/{player_id}/ for all 600+ players individually keeps this
to roughly one request per gameweek (~1-38 requests) instead of 600+.
"""

import sqlite3
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://fantasy.premierleague.com/api"
DB_PATH = Path(__file__).parent / "fpl_form.db"
REQUEST_DELAY_SECONDS = 0.3  # be polite to the API between gameweek calls
TIMEOUT = 15

SESSION = requests.Session()
SESSION.headers.update(
    {
        # A browser-like UA avoids occasional 403s from the API.
        "User-Agent": (
            "Mozilla/5.0 (compatible; FPLFormTracker/1.0; "
            "+https://fantasy.premierleague.com/)"
        )
    }
)


def get_json(path: str) -> dict:
    url = f"{BASE_URL}/{path}"
    resp = SESSION.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            name TEXT,
            short_name TEXT
        );

        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY,
            singular_name TEXT,
            short_name TEXT
        );

        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            second_name TEXT,
            web_name TEXT,
            team_id INTEGER,
            position_id INTEGER,
            now_cost INTEGER,
            status TEXT,
            fpl_form REAL,
            points_per_game REAL,
            selected_by_percent REAL,
            FOREIGN KEY (team_id) REFERENCES teams (id),
            FOREIGN KEY (position_id) REFERENCES positions (id)
        );

        CREATE TABLE IF NOT EXISTS gameweeks (
            id INTEGER PRIMARY KEY,
            name TEXT,
            deadline_time TEXT,
            finished INTEGER,
            is_current INTEGER
        );

        -- One row per player per gameweek they had a fixture in.
        CREATE TABLE IF NOT EXISTS player_gameweek_stats (
            player_id INTEGER,
            gameweek_id INTEGER,
            total_points INTEGER,
            minutes INTEGER,
            goals_scored INTEGER,
            assists INTEGER,
            clean_sheets INTEGER,
            goals_conceded INTEGER,
            bonus INTEGER,
            PRIMARY KEY (player_id, gameweek_id)
        );

        CREATE INDEX IF NOT EXISTS idx_pgs_gameweek
            ON player_gameweek_stats (gameweek_id);
        CREATE INDEX IF NOT EXISTS idx_pgs_player
            ON player_gameweek_stats (player_id);
        """
    )
    conn.commit()

    # Migration for databases created before fpl_form/points_per_game/
    # selected_by_percent existed on the players table.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    for col, col_type in (
        ("fpl_form", "REAL"),
        ("points_per_game", "REAL"),
        ("selected_by_percent", "REAL"),
    ):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE players ADD COLUMN {col} {col_type}")
    conn.commit()


def load_bootstrap(conn: sqlite3.Connection) -> list[int]:
    """Load teams, positions, players, gameweeks. Returns finished gameweek IDs."""
    print("Fetching bootstrap-static (players, teams, gameweeks) ...")
    data = get_json("bootstrap-static/")

    conn.executemany(
        "INSERT OR REPLACE INTO teams (id, name, short_name) VALUES (?, ?, ?)",
        [(t["id"], t["name"], t["short_name"]) for t in data["teams"]],
    )

    conn.executemany(
        "INSERT OR REPLACE INTO positions (id, singular_name, short_name) "
        "VALUES (?, ?, ?)",
        [
            (p["id"], p["singular_name"], p["singular_name_short"])
            for p in data["element_types"]
        ],
    )

    conn.executemany(
        """INSERT OR REPLACE INTO players
           (id, first_name, second_name, web_name, team_id, position_id,
            now_cost, status, fpl_form, points_per_game, selected_by_percent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                p["id"],
                p["first_name"],
                p["second_name"],
                p["web_name"],
                p["team"],
                p["element_type"],
                p["now_cost"],
                p["status"],
                float(p["form"]) if p.get("form") not in (None, "") else None,
                float(p["points_per_game"])
                if p.get("points_per_game") not in (None, "")
                else None,
                float(p["selected_by_percent"])
                if p.get("selected_by_percent") not in (None, "")
                else None,
            )
            for p in data["elements"]
        ],
    )

    conn.executemany(
        """INSERT OR REPLACE INTO gameweeks
           (id, name, deadline_time, finished, is_current)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                e["id"],
                e["name"],
                e["deadline_time"],
                1 if e["finished"] else 0,
                1 if e["is_current"] else 0,
            )
            for e in data["events"]
        ],
    )
    conn.commit()

    finished_ids = [e["id"] for e in data["events"] if e["finished"]]
    print(
        f"Loaded {len(data['elements'])} players, {len(data['teams'])} teams, "
        f"{len(finished_ids)} finished gameweeks."
    )
    return finished_ids


def load_gameweek_live(conn: sqlite3.Connection, gw_id: int) -> int:
    """Fetch live stats for one gameweek, return number of rows written."""
    data = get_json(f"event/{gw_id}/live/")
    rows = []
    for el in data["elements"]:
        stats = el["stats"]
        rows.append(
            (
                el["id"],
                gw_id,
                stats["total_points"],
                stats["minutes"],
                stats["goals_scored"],
                stats["assists"],
                stats["clean_sheets"],
                stats["goals_conceded"],
                stats["bonus"],
            )
        )

    conn.executemany(
        """INSERT OR REPLACE INTO player_gameweek_stats
           (player_id, gameweek_id, total_points, minutes, goals_scored,
            assists, clean_sheets, goals_conceded, bonus)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def refresh_all_data(db_path: Path = DB_PATH, progress_callback=None) -> None:
    """
    Fetch everything (players, teams, gameweeks, per-gameweek stats) and
    write it to db_path. Importable so app.py can trigger a refresh from
    a button click (e.g. when running on Streamlit Community Cloud, where
    there's no terminal to run this script separately).

    progress_callback, if given, is called as progress_callback(message)
    after each step — handy for showing status in a Streamlit UI.
    """

    def report(msg: str) -> None:
        print(msg)
        if progress_callback:
            progress_callback(msg)

    conn = sqlite3.connect(db_path)
    init_db(conn)

    report("Fetching players, teams, and gameweeks...")
    finished_gw_ids = load_bootstrap(conn)

    if not finished_gw_ids:
        report("No finished gameweeks yet this season — nothing to load.")
        conn.close()
        return

    report(f"Fetching stats for {len(finished_gw_ids)} gameweek(s)...")
    for gw_id in finished_gw_ids:
        n = load_gameweek_live(conn, gw_id)
        report(f"  GW{gw_id}: {n} player rows")
        time.sleep(REQUEST_DELAY_SECONDS)

    conn.close()
    report(f"Done. Data stored in {db_path}")


def main() -> None:
    try:
        refresh_all_data()
    except requests.RequestException as exc:
        print(f"Failed to fetch data: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
