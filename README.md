# Scoreless Results

Win/loss results for your favorite teams — never the score.

- `scripts/update_data.py` pulls every team's recent and upcoming games from ESPN's public
  API every 10 minutes (via GitHub Actions) into `data/<league>.json`. For finished games it
  stores only which side won (and whether it went to overtime); scores are never copied.
- `scripts/update_standings.py` does the same for NBA / NHL / NFL standings → `standings.json`.
- `index.html` shows the teams you chose, hidden until tapped. In-progress games update by
  themselves straight from ESPN (period, an optional "worth watching" flag, final result).
- `teams.html` lets you pick leagues and teams; the choice is saved in your browser.
- `standings.html` shows conference/division standings and the playoff picture.

Leagues are defined in `LEAGUES` at the top of `scripts/update_data.py`.
