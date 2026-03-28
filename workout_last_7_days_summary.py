#!/usr/bin/env python3
"""
workout_last_7_days_summary.py
-------------------------------
Summarise workout totals for the last N days (default: 7) from
`data/exercise_workouts.csv` produced by `extract_exercise_data.py`.

Output: `analysis/workout_last_7_days.csv` by default.

Day assignment:
  - Uses `startDate` local date (from the ISO timestamp in the CSV).

Columns:
  - `Day` (e.g. "Monday, 20 mar 2026")
  - `Exercises` (e.g. "Running (23 min, 4.2 km, 310 kcal, avgHR 152, avgP 280 W)")
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


DATA_DIR = Path("data")
ANALYSIS_DIR = Path("analysis")


def parse_iso(dt_str: str) -> datetime:
    if dt_str is None or dt_str == "":
        raise ValueError("Empty datetime")
    # CSV values are isoformat with timezone offset (e.g. 2022-05-24T06:37:37+01:00)
    return datetime.fromisoformat(dt_str)


def activity_label(activity_type: str) -> str:
    """
    Turn HK workout activity types into readable labels.

    Example:
      HKWorkoutActivityTypeFunctionalStrengthTraining -> Functional Strength Training
    """
    s = (activity_type or "").strip()
    if s.startswith("HKWorkoutActivityType"):
        s = s[len("HKWorkoutActivityType") :]
    s = s.strip()
    if not s or s == "Unknown":
        return "Unknown"
    # Split CamelCase into words.
    s = "".join((" " + c if c.isupper() else c) for c in s).strip()
    return s


def safe_float(x: str) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DATA_DIR / "exercise_workouts.csv")
    parser.add_argument("--stats", type=Path, default=DATA_DIR / "exercise_workout_statistics.csv")
    parser.add_argument("--out", type=Path, default=ANALYSIS_DIR / "workout_last_7_days.csv")
    parser.add_argument("--days", type=int, default=7, help="Number of days to summarise")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    # Read all workouts once to find the latest workout date.
    rows: list[dict[str, str]] = []
    latest_day: Optional[date] = None
    duration_by_workout_id: dict[str, float] = {}
    with open(args.input, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            start_dt: Optional[datetime] = None
            try:
                if row.get("startDate"):
                    start_dt = parse_iso(row["startDate"])
            except ValueError:
                start_dt = None
            if not start_dt:
                continue
            d = start_dt.date()
            if latest_day is None or d > latest_day:
                latest_day = d
            wid = (row.get("workout_id") or "").strip()
            dur = safe_float(row.get("durationMinutes") or "")
            if wid and dur is not None:
                duration_by_workout_id[wid] = dur
            rows.append(row)

    if not latest_day:
        print("No valid startDate rows found in input.", file=sys.stderr)
        sys.exit(1)

    day_list = [latest_day - timedelta(days=i) for i in range(args.days - 1, -1, -1)]
    day_set = set(day_list)

    count_by_day: dict[date, int] = {}
    per_activity_by_day: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    # Stats aggregations (day, activity) -> values
    kcal_by_day_activity: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    km_by_day_activity: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    hr_weighted_sum_by_day_activity: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    hr_weight_by_day_activity: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    power_weighted_sum_by_day_activity: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    power_weight_by_day_activity: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    # Map workout_id -> (day, activity) for joining in statistics.
    workout_id_to_day_activity: dict[str, tuple[date, str]] = {}

    for row in rows:
        try:
            start_dt = parse_iso(row["startDate"])
        except Exception:
            continue
        d = start_dt.date()
        if d not in day_set:
            continue

        activity = (row.get("workout_activity_type") or "").strip()
        if not activity:
            activity = "Unknown"

        duration_minutes_str = (row.get("durationMinutes") or "").strip()
        try:
            duration_min = float(duration_minutes_str) if duration_minutes_str else 0.0
        except ValueError:
            duration_min = 0.0

        per_activity_by_day[d][activity] += duration_min
        count_by_day[d] = count_by_day.get(d, 0) + 1

        wid = (row.get("workout_id") or "").strip()
        if wid:
            workout_id_to_day_activity[wid] = (d, activity)

    # Load workout statistics (if present) and aggregate onto (day, activity).
    if args.stats.exists():
        with open(args.stats, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                wid = (row.get("workout_id") or "").strip()
                if not wid or wid not in workout_id_to_day_activity:
                    continue
                d, activity = workout_id_to_day_activity[wid]
                stat_type = (row.get("stat_type") or "").strip()
                unit = (row.get("unit") or "").strip()

                # Energy
                if stat_type == "HKQuantityTypeIdentifierActiveEnergyBurned":
                    v = safe_float(row.get("sum") or "")
                    if v is not None and unit.lower() == "kcal":
                        kcal_by_day_activity[d][activity] += v
                    continue

                # Distance
                if stat_type.startswith("HKQuantityTypeIdentifierDistance"):
                    v = safe_float(row.get("sum") or "")
                    if v is None:
                        continue
                    if unit.lower() == "m":
                        v = v / 1000.0
                    elif unit.lower() != "km":
                        continue
                    km_by_day_activity[d][activity] += v
                    continue

                # Avg heart rate
                if stat_type == "HKQuantityTypeIdentifierHeartRate":
                    avg = safe_float(row.get("average") or "")
                    if avg is None:
                        continue
                    dur = duration_by_workout_id.get(wid)
                    if dur is None or dur <= 0:
                        continue
                    hr_weighted_sum_by_day_activity[d][activity] += avg * dur
                    hr_weight_by_day_activity[d][activity] += dur
                    continue

                # Avg running power
                if stat_type == "HKQuantityTypeIdentifierRunningPower":
                    avg = safe_float(row.get("average") or "")
                    if avg is None:
                        continue
                    dur = duration_by_workout_id.get(wid)
                    if dur is None or dur <= 0:
                        continue
                    power_weighted_sum_by_day_activity[d][activity] += avg * dur
                    power_weight_by_day_activity[d][activity] += dur
                    continue

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Day", "Exercises"])

        for d in day_list:
            per_activity = per_activity_by_day[d]
            items = [(act, mins) for act, mins in per_activity.items() if mins > 0.01]
            items.sort(key=lambda x: (-x[1], activity_label(x[0]).lower()))

            parts = []
            for act, mins in items:
                bits = [f"{int(round(mins))} min"]

                km = km_by_day_activity[d].get(act)
                if km is not None and km > 0.01:
                    bits.append(f"{km:.1f} km")

                kcal = kcal_by_day_activity[d].get(act)
                if kcal is not None and kcal > 0.5:
                    bits.append(f"{int(round(kcal))} kcal")

                hr_w = hr_weight_by_day_activity[d].get(act, 0.0)
                if hr_w > 0:
                    avg_hr = hr_weighted_sum_by_day_activity[d][act] / hr_w
                    bits.append(f"avgHR {int(round(avg_hr))}")

                p_w = power_weight_by_day_activity[d].get(act, 0.0)
                if p_w > 0:
                    avg_p = power_weighted_sum_by_day_activity[d][act] / p_w
                    bits.append(f"avgP {int(round(avg_p))} W")

                parts.append(f"{activity_label(act)} ({', '.join(bits)})")

            exercises = ", ".join(parts)
            day_str = f"{d.strftime('%A')}, {d.day} {d.strftime('%b').lower()} {d.year}"
            writer.writerow([day_str, exercises])

    print(f"Wrote workout summary to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

