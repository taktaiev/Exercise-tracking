"""
process_health.py - reads workouts from Gist (no auth needed if Gist is public)
or falls back to empty data so the dashboard still deploys.
"""

import json
import os
import urllib.request
from datetime import date, timedelta, datetime

GIST_RAW_URL  = os.environ.get("GIST_RAW_URL", "")
SHEET_CSV_URL = os.environ.get("SHEET_CSV_URL", "")

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

def fetch_workouts():
    if not GIST_RAW_URL:
        print("No GIST_RAW_URL set, using empty workout list.")
        return []
    try:
        with urllib.request.urlopen(GIST_RAW_URL) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"Could not fetch Gist: {e}. Using empty workout list.")
        return []

def fetch_sheet_overrides():
    if not SHEET_CSV_URL:
        return {}
    try:
        with urllib.request.urlopen(SHEET_CSV_URL) as r:
            lines = r.read().decode("utf-8").splitlines()
        if len(lines) < 2:
            return {}
        headers = [h.strip().lower() for h in lines[0].split(",")]
        overrides = {}
        for line in lines[1:]:
            parts = line.split(",")
            row = {headers[i]: parts[i].strip() if i < len(parts) else "" for i in range(len(headers))}
            if row.get("date"):
                overrides[row["date"]] = row
        return overrides
    except Exception as e:
        print(f"Could not fetch overrides: {e}")
        return {}

def build_day_record(day_str, workouts, overrides):
    d = date.fromisoformat(day_str)
    is_sunday = d.weekday() == 6
    total_cals = round(sum(w.get("calories", 0) for w in workouts))
    total_mins = round(sum(w.get("duration_minutes", 0) for w in workouts))
    types_today = [w.get("workout_type", "") for w in workouts]
    real_today = [t for t in types_today if t in REAL_WORKOUT_TYPES]
    walk_today = [t for t in types_today if t in WALKING_TYPES]
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
        "date": day_str,
        "is_sunday": is_sunday,
        "exercise_done": exercise_class in ("real", "walk"),
        "exercise_class": "off" if is_sunday else exercise_class,
        "workout_type": DISPLAY_NAMES.get(primary_type, primary_type) if primary_type else None,
        "is_real": exercise_class == "real",
        "calories": total_cals,
        "minutes": total_mins,
        "notes": None,
        "overridden": False,
        "streak": 0,
        "is_streak_record": False,
        "is_calorie_record": False,
        "is_duration_record": False,
    }
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
            try: record["calories"] = int(float(ov["calories"]))
            except ValueError: pass
        if ov.get("minutes"):
            try: record["minutes"] = int(float(ov["minutes"]))
            except ValueError: pass
        if ov.get("notes"):
            record["notes"] = ov["notes"]
    return record

def compute_streaks(days):
    streak = 0
    max_streak = 0
    for d in days:
        if d["is_sunday"]:
            d["streak"] = streak
            continue
        streak = streak + 1 if d["exercise_done"] else 0
        d["streak"] = streak
        if streak > max_streak:
            max_streak = streak
    for d in days:
        d["is_streak_record"] = d.get("streak", 0) == max_streak and max_streak > 1
    return days

def compute_records(days):
    max_cals = max_mins = 0
    cal_date = min_date = None
    for d in days:
        if d["calories"] > max_cals:
            max_cals = d["calories"]; cal_date = d["date"]
        if d["minutes"] > max_mins:
            max_mins = d["minutes"]; min_date = d["date"]
    for d in days:
        d["is_calorie_record"] = d["date"] == cal_date
        d["is_duration_record"] = d["date"] == min_date
    return days

def main():
    print("Fetching workouts…")
    raw_workouts = fetch_workouts()
    by_date = {}
    for w in raw_workouts:
        day = w.get("date", "")[:10]
        by_date.setdefault(day, []).append(w)

    print("Fetching overrides…")
    overrides = fetch_sheet_overrides()

    today = date.today()
    start = today - timedelta(days=364)
    days = [build_day_record((start + timedelta(days=i)).isoformat(),
                              by_date.get((start + timedelta(days=i)).isoformat(), []),
                              overrides) for i in range(365)]
    days = compute_streaks(days)
    days = compute_records(days)

    active_days = [d for d in days if d["exercise_done"] and not d["is_sunday"]]
    real_days   = [d for d in days if d["is_real"]]
    current_streak = days[-1]["streak"] if days else 0
    best_streak    = max((d.get("streak", 0) for d in days), default=0)
    avg_cals = round(sum(d["calories"] for d in active_days) / max(len(active_days), 1))
    avg_mins = round(sum(d["minutes"] for d in active_days) / max(len(active_days), 1))

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "active_days": len(active_days),
            "real_workouts": len(real_days),
            "current_streak": current_streak,
            "best_streak": best_streak,
            "avg_calories": avg_cals,
            "avg_minutes": avg_mins,
        },
        "days": days,
    }
    with open("data.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"Done. {len(days)} days written. Current streak: {current_streak}.")

if __name__ == "__main__":
    main()
