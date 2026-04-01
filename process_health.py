"""
process_health.py
Fetches workout data from a GitHub Gist (posted by iOS Shortcut),
merges with Google Sheets overrides, and writes data.json for the dashboard.
"""

import json
import os
import urllib.request
import urllib.parse
from datetime import date, timedelta, datetime

# ── Config (set these as GitHub Actions secrets / env vars) ──────────────────
GIST_ID        = os.environ["GIST_ID"]          # GitHub Gist ID
GITHUB_TOKEN   = os.environ["DATA_GITHUB_TOKEN"]  # GitHub personal access token (PAT)
SHEET_CSV_URL  = os.environ.get("SHEET_CSV_URL", "")  # Google Sheet published CSV URL

REAL_WORKOUT_TYPES = {
    "Running", "TraditionalStrengthTraining", "FunctionalStrengthTraining",
    "HighIntensityIntervalTraining", "Yoga", "Pilates",
    "CrossTraining", "MixedCardio",
}

WALKING_TYPES = {"Walking", "WalkingSpeed", "WalkingStepLength"}

DISPLAY_NAMES = {
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

# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_gist(gist_id: str, token: str) -> list[dict]:
    url = f"https://api.github.com/gists/{gist_id}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req) as r:
        gist = json.loads(r.read())
    # Expect a single file called workouts.json
    file_content = list(gist["files"].values())[0]["content"]
    return json.loads(file_content)


def fetch_sheet_overrides(csv_url: str) -> dict[str, dict]:
    """
    Google Sheet columns (row 1 = headers):
      date (YYYY-MM-DD) | exercise_done | workout_type | calories | minutes | notes
    Returns dict keyed by date string.
    """
    if not csv_url:
        return {}
    req = urllib.request.Request(csv_url)
    with urllib.request.urlopen(req) as r:
        lines = r.read().decode("utf-8").splitlines()
    overrides = {}
    if len(lines) < 2:
        return {}
    headers = [h.strip().lower() for h in lines[0].split(",")]
    for line in lines[1:]:
        parts = line.split(",")
        row = {headers[i]: parts[i].strip() if i < len(parts) else "" for i in range(len(headers))}
        if row.get("date"):
            overrides[row["date"]] = row
    return overrides


def classify(workout_type: str) -> str:
    if workout_type in REAL_WORKOUT_TYPES:
        return "real"
    if workout_type in WALKING_TYPES:
        return "walk"
    return "other"


def build_day_record(day_str: str, workouts: list[dict], overrides: dict) -> dict:
    d = date.fromisoformat(day_str)
    is_sunday = d.weekday() == 6  # Monday=0, Sunday=6

    # Aggregate from Apple Health
    total_cals = round(sum(w.get("calories", 0) for w in workouts))
    total_mins = round(sum(w.get("duration_minutes", 0) for w in workouts))

    # Determine best workout type
    types_today = [w.get("workout_type", "") for w in workouts]
    real_today  = [t for t in types_today if t in REAL_WORKOUT_TYPES]
    walk_today  = [t for t in types_today if t in WALKING_TYPES]

    if real_today:
        primary_type = real_today[0]
        exercise_class = "real"
    elif walk_today:
        primary_type = "Walking"
        exercise_class = "walk"
    else:
        primary_type = None
        exercise_class = "rest"

    record = {
        "date":           day_str,
        "is_sunday":      is_sunday,
        "exercise_done":  exercise_class in ("real", "walk"),
        "exercise_class": "off" if is_sunday else exercise_class,
        "workout_type":   DISPLAY_NAMES.get(primary_type, primary_type) if primary_type else None,
        "is_real":        exercise_class == "real",
        "calories":       total_cals,
        "minutes":        total_mins,
        "notes":          None,
        "overridden":     False,
    }

    # Apply Google Sheets override if present
    ov = overrides.get(day_str)
    if ov:
        record["overridden"] = True
        if ov.get("exercise_done"):
            record["exercise_done"] = ov["exercise_done"].lower() in ("yes", "true", "1")
        if ov.get("workout_type"):
            record["workout_type"] = ov["workout_type"]
            record["is_real"] = ov["workout_type"].lower() not in ("walking", "walk", "")
            record["exercise_class"] = "real" if record["is_real"] else "walk"
        if ov.get("calories"):
            try:
                record["calories"] = int(float(ov["calories"]))
            except ValueError:
                pass
        if ov.get("minutes"):
            try:
                record["minutes"] = int(float(ov["minutes"]))
            except ValueError:
                pass
        if ov.get("notes"):
            record["notes"] = ov["notes"]

    return record


def compute_streaks(days: list[dict]) -> list[dict]:
    """Tag each day with current streak length and whether it's a personal record."""
    streak = 0
    max_streak = 0
    for d in days:
        if d["is_sunday"]:
            # Sunday doesn't break or count towards streak
            d["streak"] = streak
            continue
        if d["exercise_done"]:
            streak += 1
        else:
            streak = 0
        d["streak"] = streak
        if streak > max_streak:
            max_streak = streak
    # Tag streak record days
    for d in days:
        d["is_streak_record"] = d.get("streak", 0) == max_streak and max_streak > 1
    return days


def compute_records(days: list[dict]) -> list[dict]:
    """Tag days with calorie or duration records."""
    max_cals = 0
    max_mins = 0
    cal_record_date = None
    min_record_date = None
    for d in days:
        if d["calories"] > max_cals:
            max_cals = d["calories"]
            cal_record_date = d["date"]
        if d["minutes"] > max_mins:
            max_mins = d["minutes"]
            min_record_date = d["date"]
    for d in days:
        d["is_calorie_record"] = d["date"] == cal_record_date
        d["is_duration_record"] = d["date"] == min_record_date
    return days


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Fetching workouts from Gist…")
    raw_workouts = fetch_gist(GIST_ID, GITHUB_TOKEN)

    # Group workouts by date
    by_date: dict[str, list] = {}
    for w in raw_workouts:
        day = w.get("date", "")[:10]  # YYYY-MM-DD
        by_date.setdefault(day, []).append(w)

    print("Fetching Google Sheets overrides…")
    overrides = fetch_sheet_overrides(SHEET_CSV_URL)

    # Build full year of records
    today = date.today()
    start = today - timedelta(days=364)
    days = []
    for i in range(365):
        day = start + timedelta(days=i)
        day_str = day.isoformat()
        workouts_today = by_date.get(day_str, [])
        days.append(build_day_record(day_str, workouts_today, overrides))

    days = compute_streaks(days)
    days = compute_records(days)

    # Summary stats
    active_days   = [d for d in days if d["exercise_done"] and not d["is_sunday"]]
    real_days     = [d for d in days if d["is_real"]]
    current_streak = days[-1]["streak"] if days else 0
    best_streak    = max((d.get("streak", 0) for d in days), default=0)
    avg_calories   = round(sum(d["calories"] for d in active_days) / max(len(active_days), 1))
    avg_minutes    = round(sum(d["minutes"] for d in active_days) / max(len(active_days), 1))

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "active_days":     len(active_days),
            "real_workouts":   len(real_days),
            "current_streak":  current_streak,
            "best_streak":     best_streak,
            "avg_calories":    avg_calories,
            "avg_minutes":     avg_minutes,
        },
        "days": days,
    }

    with open("data.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Done. {len(days)} days written. Current streak: {current_streak}.")


if __name__ == "__main__":
    main()
