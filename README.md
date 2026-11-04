# Spoiler-Free Scores

Shows win/loss results for a few favorite teams — never the score.

- `scripts/update_results.py` pulls schedules from ESPN's public API every 10 minutes
  (via GitHub Actions), keeps only W / L / T / OTL, and writes `results.json`.
  Scores are never copied, so they can't leak to the site or into git history.
- `index.html` reads `results.json`. Results stay hidden until a team is tapped.

Edit the `TEAMS` list in `scripts/update_results.py` to change teams.
