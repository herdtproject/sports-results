#!/usr/bin/env python3
"""Build data/<league>.json for every team in each league from ESPN.

Per team we keep only its last few finished games and its next few games.

SPOILER SAFETY: for a finished game only the winning side (home / away / tie)
and an overtime flag are stored. Scores are never written. For a live game only
the period, who is leading and whether it is close are stored.
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://site.api.espn.com/apis/site/v2/sports"
FBS_STANDINGS = "https://site.api.espn.com/apis/v2/sports/football/college-football/standings?group=80"
DATA = Path(__file__).resolve().parent.parent / "data"

# key, ESPN path, extra scoreboard query, (period prefix, regulation periods)
LEAGUES = [
    ("NBA", "basketball/nba", "", ("Q", 4)),
    ("NFL", "football/nfl", "", ("Q", 4)),
    ("NHL", "hockey/nhl", "", ("P", 3)),
    ("NCAAF", "football/college-football", "&groups=80", ("Q", 4)),
]
KEEP_PAST, KEEP_FUTURE = 4, 4
BACK_MONTHS, FWD_MONTHS = 9, 9  # how far a full refresh looks
SKIP = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED", "STATUS_FORFEIT"}
MARKETS = {"national": "n", "home": "h", "away": "a"}


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sports-results/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def logo(team):
    if team.get("logo"):
        return team["logo"]
    return team["logos"][0]["href"] if team.get("logos") else None


def team_entry(t):
    return {"n": t.get("displayName") or t.get("name"), "a": t.get("abbreviation"), "l": logo(t)}


def months(today):
    out, y, m = [], today.year, today.month - BACK_MONTHS
    while m < 1:
        y, m = y - 1, m + 12
    for _ in range(BACK_MONTHS + FWD_MONTHS + 1):
        out.append(f"{y}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def parse(ev, periods):
    comp = ev["competitions"][0]
    st = comp["status"]
    if st["type"]["name"] in SKIP:
        return None, {}
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    if "home" not in sides or "away" not in sides:
        return None, {}
    seen = {c["team"]["id"]: team_entry(c["team"]) for c in comp["competitors"]}
    h, a = sides["home"], sides["away"]
    g = {"id": ev["id"], "d": ev["date"], "h": h["team"]["id"], "a": a["team"]["id"]}
    if st["type"]["completed"]:
        g["s"] = "f"
        g["w"] = "h" if h.get("winner") else "a" if a.get("winner") else "t"
        if re.search(r"OT|SO", st["type"].get("detail", "")):
            g["o"] = 1
    elif st["type"]["state"] == "in":
        g["s"] = "l"
        prefix, regulation = periods
        if isinstance(st.get("period"), int) and st["period"] >= 1:
            g["p"] = f"{prefix}{min(st['period'], regulation)}"
        try:  # reduce the live score to "who leads" + "is it close"; never stored
            hs, as_ = float(h["score"]), float(a["score"])
            g["l"] = "h" if hs > as_ else "a" if as_ > hs else "t"
            if abs(hs - as_) < 8:
                g["c"] = 1
        except (KeyError, ValueError, TypeError):
            pass
    else:
        g["s"] = "u"
    if g["s"] != "f":
        tv = {}
        for b in comp.get("broadcasts", []):
            k = MARKETS.get(b.get("market"))
            if k:
                for n in b.get("names", []):
                    if n not in tv.setdefault(k, []):
                        tv[k].append(n)
        if tv:
            g["tv"] = tv
    return g, seen


def prune(games, pick):
    """Keep each team's last few finals and next few games (plus anything live)."""
    keep = set()
    for tid in pick:
        mine = sorted((g for g in games.values() if tid in (g["h"], g["a"])), key=lambda g: g["d"])
        finals = [g for g in mine if g["s"] == "f"]
        ahead = [g for g in mine if g["s"] != "f"]
        keep.update(g["id"] for g in finals[-KEEP_PAST:])
        keep.update(g["id"] for g in ahead[:KEEP_FUTURE])
        keep.update(g["id"] for g in mine if g["s"] == "l")
    return {i: g for i, g in games.items() if i in keep}


def pick_teams(path, key):
    """Every team that can be chosen on the Teams page."""
    if key == "NCAAF":  # ESPN's team list is incomplete for college; use the FBS standings
        teams = {}

        def walk(n):
            for e in n.get("standings", {}).get("entries", []):
                teams[e["team"]["id"]] = team_entry(e["team"])
            for c in n.get("children", []):
                walk(c)
        walk(get(FBS_STANDINGS))
        return teams
    data = get(f"{BASE}/{path}/teams?limit=500")
    return {t["team"]["id"]: team_entry(t["team"]) for t in data["sports"][0]["leagues"][0]["teams"]}


def build(key, path, extra, periods, today):
    out = DATA / f"{key.lower()}.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    games = {g["id"]: g for g in old.get("games", [])}
    teams = dict(old.get("teams", {}))
    full = old.get("fullAt") != today.strftime("%Y-%m-%d")
    if full:
        wanted = months(today)
    else:
        wanted = [today.strftime("%Y%m")]
        if today.day <= 2:
            wanted.insert(0, (today.replace(day=1) - timedelta(days=1)).strftime("%Y%m"))
    fresh, fetched = {}, []
    for ym in wanted:
        try:
            data = get(f"{BASE}/{path}/scoreboard?dates={ym}&limit=500{extra}")
        except Exception as exc:
            if not full:
                raise  # a routine run must not publish stale data silently
            print(f"  ({key} {ym} skipped: {exc})", file=sys.stderr)
            continue
        fetched.append(ym)
        for ev in data.get("events", []):
            g, seen = parse(ev, periods)
            if g:
                fresh[g["id"]] = g
                teams.update(seen)
    if fetched:
        lo = datetime.strptime(fetched[0] + "01", "%Y%m%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        ly, lm = int(fetched[-1][:4]), int(fetched[-1][4:])
        hi = datetime(ly + (lm == 12), lm % 12 + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        for i in list(games):  # drop games ESPN no longer lists inside the fetched range
            d = datetime.strptime(games[i]["d"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            if lo <= d <= hi and i not in fresh:
                del games[i]
    games.update(fresh)

    pick = pick_teams(path, key)
    teams.update(pick)
    games = prune(games, pick)
    used = {t for g in games.values() for t in (g["h"], g["a"])} | set(pick)
    new = {
        "league": key,
        "path": path,
        "fullAt": today.strftime("%Y-%m-%d") if full and fetched else old.get("fullAt"),
        "teams": {i: teams[i] for i in sorted(used) if i in teams},
        "pick": sorted(pick, key=lambda i: pick[i]["n"]),
        "games": sorted(games.values(), key=lambda g: (g["d"], g["id"])),
    }
    if {k: v for k, v in old.items() if k != "updated"} == new:
        print(f"{key}: no changes", file=sys.stderr)
        return
    new["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    # One game per line keeps the git diffs small.
    head = {k: v for k, v in new.items() if k != "games"}
    text = json.dumps(head, separators=(",", ":"))[:-1] + ',"games":[\n'
    text += ",\n".join(json.dumps(g, separators=(",", ":")) for g in new["games"]) + "\n]}\n"
    out.write_text(text)
    print(f"{key}: wrote {len(new['games'])} games, {len(new['teams'])} teams", file=sys.stderr)


def main():
    DATA.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc)
    for key, path, extra, periods in LEAGUES:
        print(f"{key}…", file=sys.stderr)
        try:
            build(key, path, extra, periods, today)
        except Exception as exc:
            print(f"ERROR for {key}: {exc}", file=sys.stderr)
            return 1  # keep the previous files rather than publish partial data
    return 0


if __name__ == "__main__":
    sys.exit(main())
