#!/usr/bin/env python3
"""Fetch schedules from ESPN and write results.json.

SPOILER SAFETY: only a result code (W / L / T / OTL), the opponent, the date
and logos are ever written out. Scores are never copied from the ESPN
response, so they cannot reach the repo, the site, or the browser.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://site.api.espn.com/apis/site/v2/sports"
OUT = Path(__file__).resolve().parent.parent / "results.json"
PAST, FUTURE = 3, 3

# name, sport/league path, ESPN team id, short league label
TEAMS = [
    ("Utah Jazz", "basketball/nba", "utah", "NBA"),
    ("Buffalo Bills", "football/nfl", "buf", "NFL"),
    ("Utah Mammoth", "hockey/nhl", "utah", "NHL"),
    ("BYU Cougars", "football/college-football", "252", "NCAAF"),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sports-results/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_events(path, tid, extra=""):
    try:
        return get(f"{BASE}/{path}/teams/{tid}/schedule{extra}").get("events", [])
    except Exception as exc:  # postseason / prior season may legitimately 404
        print(f"  (skipped {extra or 'default'}: {exc})", file=sys.stderr)
        return []


def season_year(path, tid):
    try:
        return get(f"{BASE}/{path}/teams/{tid}/schedule")["season"]["year"]
    except Exception:
        return None


def logo(team):
    if team.get("logo"):
        return team["logo"]
    for l in team.get("logos", []):
        if "default" in l.get("rel", []):
            return l["href"]
    return team["logos"][0]["href"] if team.get("logos") else None


def parse(ev, tid):
    comp = ev["competitions"][0]
    me = next((c for c in comp["competitors"] if c["team"]["id"] == tid), None)
    opp = next((c for c in comp["competitors"] if c is not me), None)
    if me is None or opp is None:
        return None
    st = comp["status"]["type"]
    g = {
        "id": ev["id"],
        "date": ev["date"],
        "home": me["homeAway"] == "home",
        "opponent": opp["team"].get("displayName") or opp["team"].get("name"),
        "opponentAbbr": opp["team"].get("abbreviation"),
        "opponentLogo": logo(opp["team"]),
    }
    name = st["name"]
    if name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
        return None
    if st["completed"]:
        g["state"] = "final"
        g["result"] = (
            "W" if me.get("winner") else "L" if opp.get("winner") else "T"
        )
        g["_detail"] = st.get("detail", "")
    elif st["state"] == "in":
        g["state"] = "live"
    else:
        g["state"] = "upcoming"
    return g


def build_team(name, path, tid, league):
    print(f"{name}…", file=sys.stderr)
    info = get(f"{BASE}/{path}/teams/{tid}")["team"]
    slug = tid
    tid = str(info["id"])  # numeric id, used to find our team in each game
    tid_path = slug
    events = fetch_events(path, tid_path) + fetch_events(path, tid_path, "?seasontype=3")
    year = season_year(path, tid_path)
    games = [g for g in (parse(e, tid) for e in events) if g]
    # Near a season boundary, borrow from the neighbouring season.
    if year and sum(g["state"] == "final" for g in games) < PAST:
        for extra in (f"?season={year-1}", f"?season={year-1}&seasontype=3"):
            games += [g for g in (parse(e, tid) for e in fetch_events(path, tid_path, extra)) if g]
    if year and sum(g["state"] != "final" for g in games) < FUTURE:
        games += [g for g in (parse(e, tid) for e in fetch_events(path, tid_path, f"?season={year+1}")) if g]

    seen, uniq = set(), []
    for g in games:
        if g["id"] not in seen:
            seen.add(g["id"])
            uniq.append(g)
    uniq.sort(key=lambda g: g["date"])

    finals = [g for g in uniq if g["state"] == "final"][-PAST:]
    ahead = [g for g in uniq if g["state"] in ("live", "upcoming")][:FUTURE]
    for g in finals:
        # Hockey: a loss in overtime or a shootout is an OTL, not an L.
        if league == "NHL" and g["result"] == "L" and any(
            k in g["_detail"] for k in ("OT", "SO")
        ):
            g["result"] = "OTL"
    for g in finals:
        g.pop("_detail", None)

    return {
        "name": name,
        "league": league,
        "logo": logo(info),
        "color": "#" + info["color"] if info.get("color") else None,
        "recent": list(reversed(finals)),  # most recent first
        "upcoming": ahead,
    }


def main():
    teams = []
    for t in TEAMS:
        try:
            teams.append(build_team(*t))
        except Exception as exc:
            print(f"ERROR for {t[0]}: {exc}", file=sys.stderr)
            return 1  # keep the previous results.json rather than publish a partial one
    new = {"teams": teams}
    if OUT.exists():
        old = json.loads(OUT.read_text())
        if {k: v for k, v in old.items() if k != "updated"} == new:
            print("No changes.", file=sys.stderr)
            return 0
    new["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    OUT.write_text(json.dumps(new, indent=2) + "\n")
    print("Wrote results.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
