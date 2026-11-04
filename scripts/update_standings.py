#!/usr/bin/env python3
"""Fetch NBA / NHL / NFL standings from ESPN and write standings.json.

Only records, standings points / win %, streak and playoff position are kept.
Points for/against and anything else score-like is never copied.
The page hides the standings behind a tap, because a record can reveal a result.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "standings.json"
URL = "https://site.api.espn.com/apis/v2/sports/{path}/standings?level=3"

LEAGUES = [
    # key, ESPN path, label for the tie-break column
    ("NBA", "basketball/nba"),
    ("NHL", "hockey/nhl"),
    ("NFL", "football/nfl"),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sports-results/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def stat(entry, name, default=None):
    for s in entry.get("stats", []):
        if s.get("name") == name:
            return s.get("displayValue", default)
    return default


def to_int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def logo(team):
    for l in team.get("logos", []):
        if "default" in l.get("rel", []):
            return l["href"]
    return team["logos"][0]["href"] if team.get("logos") else None


def team_row(league, e):
    t = e["team"]
    w, l = to_int(stat(e, "wins")), to_int(stat(e, "losses"))
    if league == "NHL":
        record = f"{w}-{l}-{to_int(stat(e, 'otLosses'))}"
        main = stat(e, "points", "0")
        main_label = "PTS"
    else:
        ties = to_int(stat(e, "ties"))
        record = f"{w}-{l}" + (f"-{ties}" if ties else "")
        main = stat(e, "winPercent", "")
        main_label = "PCT"
    return {
        "id": str(t["id"]),
        "name": t.get("shortDisplayName") or t["displayName"],
        "abbr": t.get("abbreviation"),
        "logo": logo(t),
        "record": record,
        "main": main,
        "mainLabel": main_label,
        "streak": stat(e, "streak", ""),
        "seed": to_int(stat(e, "playoffSeed"), 99),
    }


def by_seed(ids, teams):
    return sorted(ids, key=lambda i: teams[i]["seed"])


def build_league(key, path):
    data = get(URL.format(path=path))
    teams, confs = {}, []
    for conf in data["children"]:
        divisions = []
        for div in conf.get("children") or []:
            ids = []
            for e in div["standings"]["entries"]:
                row = team_row(key, e)
                teams[row["id"]] = row
                ids.append(row["id"])
            divisions.append({"name": div["name"].replace(conf["abbreviation"] + " ", ""), "ids": by_seed(ids, teams)})
        confs.append({"name": conf["name"], "divisions": divisions})

    lines = []
    for conf in confs:
        all_ids = by_seed([i for d in conf["divisions"] for i in d["ids"]], teams)
        if key == "NBA":
            for n, i in enumerate(all_ids, 1):
                teams[i]["status"] = "in" if n <= 6 else "playin" if n <= 10 else "out"
            order, cuts = all_ids, [6, 10]
        elif key == "NFL":
            for n, i in enumerate(all_ids, 1):
                teams[i]["status"] = "div" if n <= 4 else "wc" if n <= 7 else "out"
            order, cuts = all_ids, [7]
        else:  # NHL: top 3 per division + 2 wild cards per conference
            top3 = {i for d in conf["divisions"] for i in d["ids"][:3]}
            rest = [i for i in all_ids if i not in top3]
            wild = set(rest[:2])
            for i in all_ids:
                teams[i]["status"] = "div" if i in top3 else "wc" if i in wild else "out"
            inn = by_seed([i for i in all_ids if i in top3 or i in wild], teams)
            order, cuts = inn + [i for i in all_ids if i not in top3 and i not in wild], [8]
        conf["order"] = order
        conf["cuts"] = cuts
        for pos, i in enumerate(order, 1):
            teams[i]["rank"] = pos  # position shown in the conference view
    notes = {
        "NBA": "Top 6 in each conference clinch a playoff spot. 7–10 enter the play-in tournament (PI).",
        "NHL": "Top 3 in each division plus 2 wild cards (WC) per conference make the playoffs.",
        "NFL": "7 per conference: the 4 division winners (seeds 1–4) and 3 wild cards (WC).",
    }
    return {"key": key, "note": notes[key], "teams": teams, "conferences": confs}


def main():
    leagues = []
    for key, path in LEAGUES:
        print(f"{key}…", file=sys.stderr)
        try:
            leagues.append(build_league(key, path))
        except Exception as exc:
            print(f"ERROR for {key}: {exc}", file=sys.stderr)
            return 1  # keep the previous file rather than publish a partial one
    new = {"leagues": leagues}
    if OUT.exists():
        old = json.loads(OUT.read_text())
        if {k: v for k, v in old.items() if k != "updated"} == new:
            print("No changes.", file=sys.stderr)
            return 0
    new["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    OUT.write_text(json.dumps(new, indent=1) + "\n")
    print("Wrote standings.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
