# PL Player Form Tracker

Tracks gameweek-by-gameweek points ("form") for every Premier League player,
using the official (undocumented) Fantasy Premier League API.

## Option A: run locally (Mac/Windows/Linux with a terminal)

```bash
cd fpl-form-tracker
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
python fetch_data.py           # pulls current season data into fpl_form.db
streamlit run app.py           # opens the dashboard in your browser
```

Re-run `python fetch_data.py` any time you want fresh numbers — it's safe
to re-run and always pulls the full current-season history from the FPL API.

To automate the weekly refresh:

**macOS/Linux (cron)** — run every Monday at 9am:
```bash
crontab -e
# add this line (adjust paths):
0 9 * * 1 cd /path/to/fpl-form-tracker && venv/bin/python fetch_data.py >> fetch.log 2>&1
```

**Windows (Task Scheduler)**: create a weekly trigger that runs
`venv\Scripts\python.exe fetch_data.py` with the working directory set to
this folder.

## Option B: deploy to Streamlit Community Cloud (no terminal needed — works from an iPad)

The app fetches its own data on first load and has a "🔄 Refresh data now"
button in the sidebar, so you never need to run `fetch_data.py` by hand.

1. Create a free GitHub account if you don't have one (github.com).
2. Create a new **public** repository (e.g. `fpl-form-tracker`).
3. Upload every file in this folder to that repo — GitHub's web UI lets
   you drag and drop files, no terminal required. (Skip `fpl_form.db` and
   `venv/` if present locally — they're excluded by `.gitignore` anyway.)
4. Go to **share.streamlit.io**, sign in with your GitHub account.
5. Click "New app", pick your repo/branch, set the main file to `app.py`,
   and deploy.
6. Streamlit builds and hosts it for you at a URL like
   `https://your-app-name.streamlit.app` — open that in Safari any time,
   on any device.

Note: Streamlit Community Cloud's storage isn't guaranteed to persist
forever between app restarts, so if the dashboard ever opens with old or
missing data, just hit "🔄 Refresh data now" in the sidebar.

## Notes / limitations

- The FPL API is undocumented and unofficial — endpoints or fields could
  change without notice. If `fetch_data.py` starts failing, check
  `https://fantasy.premierleague.com/api/bootstrap-static/` in a browser
  to see if the response shape changed.
- "Form" here is defined as raw gameweek points (sum/average over your
  chosen window) — not FPL's own smoothed `form` stat.
- Players who didn't feature in a gameweek (didn't play, no fixture, etc.)
  simply have no row for that gameweek — they aren't counted as 0.
- Data only goes back to the start of the current season; historical
  seasons aren't included.

## Files

- `fetch_data.py` — pulls data from the FPL API into `fpl_form.db`
- `app.py` — Streamlit dashboard that reads from `fpl_form.db`
- `requirements.txt` — Python dependencies
- `fpl_form.db` — created after your first `fetch_data.py` run (not
  included — it's your local data)
