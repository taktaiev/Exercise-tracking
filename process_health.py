"""
process_health.py — fetch workouts from GitHub Gist, merge overrides, write data.json
"""
import json, os, urllib.request
from datetime import date, timedelta, datetime

# ── Secrets (set in GitHub repo → Settings → Secrets → Actions) ─────────────
GIST_ID   = os.environ.get("GIST_ID", "")
PAT       = os.environ.get("DATA_GITHUB_TOKEN", "")
SHEET_URL = os.environ.get("SHEET_CSV_URL", "")

REAL_TYPES = {
    "Running", "TraditionalStrengthTraining", "FunctionalStrengthTraining",
    "HighIntensityIntervalTraining", "Yoga", "Pilates", "CrossTraining", "MixedCardio",
}
WALK_TYPES = {"Walking", "WalkingSpeed", "WalkingStepLength"}
DISPLAY = {
    "Running": "Running",
    "TraditionalStrengthTraining": "Strength",
    "FunctionalStrengthTraining": "Strength",
    "HighIntensityIntervalTraining": "HIIT",
    "Yoga": "Yoga",
    "Pilates": "Yoga / Pilates",
    "CrossTraining": "HIIT",
    "MixedCardio": "HIIT",
    "Walking": "Walking",
}

def fetch_gist():
    print(f"GIST_ID  length: {len(GIST_ID)}")
    print(f"PAT      length: {len(PAT)}")
    if not GIST_ID:
        raise ValueError("GIST_ID secret is empty or not set")
    if not PAT:
        raise ValueError("DATA_GITHUB_TOKEN secret is empty or not set")
    url = f"https://api.github.com/gists/{GIST_ID}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {PAT}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req) as r:
            gist = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API returned {e.code} for gist {GIST_ID}. "
                           f"Check GIST_ID and DATA_GITHUB_TOKEN are correct.") from e
    files = gist.get("files", {})
    print(f"Gist files: {list(files.keys())}")
    for fname, fdata in files.items():
        if fname.endswith(".json") or fname == "workouts.json":
            return json.loads(fdata["content"])
    first = list(files.values())[0]
    return json.loads(first["content"])

def fetch_overrides():
    if not SHEET_URL:
        return {}
    req = urllib.request.Request(SHEET_URL)
    with urllib.request.urlopen(req) as r:
        lines = r.read().decode("utf-8").splitlines()
    if len(lines) < 2:
        return {}
    headers = [h.strip().lower() for h in lines[0].split(",")]
    overrides = {}
    for line in lines[1:]:
        parts = line.split(",")
        row = {headers[i]: (parts[i].strip() if i < len(parts) else "") for i in range(len(headers))}
        if row.get("date"):
            overrides[row["date"]] = row
    return overrides

def build_day(day_str, workouts, overrides):
    d = date.fromisoformat(day_str)
    is_sunday = d.weekday() == 6
    total_cals = round(sum(w.get("calories", 0) for w in workouts))
    total_mins = round(sum(w.get("duration_minutes", 0) for w in workouts))
    types = [w.get("workout_type", "") for w in workouts]
    real = [t for t in types if t in REAL_TYPES]
    walk = [t for t in types if t in WALK_TYPES]
    if real:
        primary, cls = real[0], "real"
    elif walk:
        primary, cls = "Walking", "walk"
    else:
        primary, cls = None, "rest"
    rec = {
        "date": day_str, "is_sunday": is_sunday,
        "exercise_done": cls in ("real", "walk"),
        "exercise_class": "off" if is_sunday else cls,
        "workout_type": DISPLAY.get(primary, primary) if primary else None,
        "is_real": cls == "real",
        "calories": total_cals, "minutes": total_mins,
        "notes": None, "overridden": False,
        "streak": 0, "is_streak_record": False,
        "is_calorie_record": False, "is_duration_record": False,
    }
    ov = overrides.get(day_str)
    if ov:
        rec["overridden"] = True
        if ov.get("exercise_done"):
            rec["exercise_done"] = ov["exercise_done"].lower() in ("yes","true","1")
        if ov.get("workout_type"):
            rec["workout_type"] = ov["workout_type"]
            rec["is_real"] = ov["workout_type"].lower() not in ("walking","walk","")
            rec["exercise_class"] = "real" if rec["is_real"] else "walk"
        for field in ("calories","minutes"):
            if ov.get(field):
                try: rec[field] = int(float(ov[field]))
                except ValueError: pass
        if ov.get("notes"): rec["notes"] = ov["notes"]
    return rec

def add_streaks(days):
    streak = max_streak = 0
    for d in days:
        if not d["is_sunday"]:
            streak = streak + 1 if d["exercise_done"] else 0
        d["streak"] = streak
        max_streak = max(max_streak, streak)
    for d in days:
        d["is_streak_record"] = d["streak"] == max_streak and max_streak > 1
    return days

def add_records(days):
    max_c = max_m = 0
    rc = rm = None
    for d in days:
        if d["calories"] > max_c: max_c, rc = d["calories"], d["date"]
        if d["minutes"] > max_m: max_m, rm = d["minutes"], d["date"]
    for d in days:
        d["is_calorie_record"]  = d["date"] == rc
        d["is_duration_record"] = d["date"] == rm
    return days

def main():
    print("Fetching workouts from Gist...")
    raw = fetch_gist()
    by_date = {}
    for w in raw:
        day = w.get("date","")[:10]
        by_date.setdefault(day, []).append(w)

    print("Fetching overrides...")
    overrides = fetch_overrides()

    today = date.today()
    days = []
    for i in range(365):
        ds = (today - timedelta(days=364-i)).isoformat()
        days.append(build_day(ds, by_date.get(ds, []), overrides))

    days = add_streaks(days)
    days = add_records(days)

    active = [d for d in days if d["exercise_done"] and not d["is_sunday"]]
    real   = [d for d in days if d["is_real"]]
    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "active_days":    len(active),
            "real_workouts":  len(real),
            "current_streak": days[-1]["streak"],
            "best_streak":    max(d["streak"] for d in days),
            "avg_calories":   round(sum(d["calories"] for d in active) / max(len(active),1)),
            "avg_minutes":    round(sum(d["minutes"]  for d in active) / max(len(active),1)),
        },
        "days": days,
    }
    with open("data.json","w") as f:
        json.dump(out, f, indent=2)
    print(f"Done. {len(days)} days. Streak: {out['summary']['current_streak']}.")

if __name__ == "__main__":
    main()
