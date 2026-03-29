#!/usr/bin/env python3
"""
sleep_night_summary.py
---------------------
Read sleep_data.csv and produce a compact last-7-days summary CSV with:
  - Weekday
  - Time fell asleep
  - Time woke up
  - Awake during night (hh:mm)
  - Total sleep (hh:mm)
  - Sleep stage durations (hh:mm): Deep, Core, REM

Usage:
    python3 sleep_night_summary.py [sleep_data.csv]

Defaults: input data/sleep_data.csv, output analysis/sleep_last_7_days.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Day boundary for assigning sleep to a date: 18:00–18:00 (e.g. Sat 23:00 → Sun 07:00 belongs to Sunday)
DAY_CUTOFF_HOUR = 18

# A single Awake stretch longer than this is reported as an "out of bed" period.
OUT_OF_BED_THRESHOLD_MIN = 40

# Default directories
DATA_DIR = Path("data")
ANALYSIS_DIR = Path("analysis")


def parse_iso(s: str) -> datetime:
    """Parse ISO datetime string (e.g. 2016-09-16T21:30:00+01:00)."""
    if s is None or s == "":
        raise ValueError("Empty datetime")
    return datetime.fromisoformat(s)


def date_only(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def sleep_date(dt: datetime) -> str:
    """Assign a datetime to a sleep-day date using 18:00–18:00 boundary.
    E.g. Sat 23:00 or Sun 07:00 both belong to Sunday (2026-02-22).
    Converts to local time first so DST-adjusted wall-clock hours are used."""
    local = dt.astimezone()
    if local.hour >= DAY_CUTOFF_HOUR:
        return (local.date() + timedelta(days=1)).strftime("%Y-%m-%d")
    return local.strftime("%Y-%m-%d")


def minutes_to_hhmm(minutes: float) -> str:
    """Convert minutes (float) to zero-padded HH:MM string."""
    total_minutes = int(round(minutes))
    hours = total_minutes // 60
    mins = total_minutes % 60
    return f"{hours:02d}:{mins:02d}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DATA_DIR / "sleep_data.csv")
    parser.add_argument("--days", type=int, default=7, help="Number of nights to summarise")
    args = parser.parse_args(argv)

    input_path = args.input
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    rows = []
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                start = parse_iso(row["StartDate"])
                end = parse_iso(row["EndDate"])
                duration = float(row["DurationMinutes"])
                value = row["Value"].strip()
            except (KeyError, ValueError) as e:
                continue
            rows.append({"start": start, "end": end, "duration": duration, "value": value})

    # Group InBed segments by sleep-day date (18:00–18:00 boundary: e.g. Sat evening → Sun morning = Sunday)
    nights = defaultdict(list)  # sleep_date -> list of InBed {start, end}
    for r in rows:
        if r["value"] != "InBed":
            continue
        wake_date = sleep_date(r["end"])
        nights[wake_date].append({"start": r["start"], "end": r["end"]})

    # For each night: first in-bed time, last out-of-bed time
    night_ranges = {}
    for wake_date, inbeds in sorted(nights.items()):
        night_ranges[wake_date] = {
            "inbed_start": min(x["start"] for x in inbeds),
            "inbed_end": max(x["end"] for x in inbeds),
        }

    # Fallback: nights with sleep stage/Awake data but no InBed — infer range from segment times
    segment_values = ("AsleepCore", "AsleepDeep", "AsleepREM", "Awake")
    orphan_starts = defaultdict(list)
    orphan_ends = defaultdict(list)
    for r in rows:
        if r["value"] not in segment_values:
            continue
        wake_date = sleep_date(r["end"])
        if wake_date in night_ranges:
            continue
        orphan_starts[wake_date].append(r["start"])
        orphan_ends[wake_date].append(r["end"])
    for wake_date in orphan_starts:
        night_ranges[wake_date] = {
            "inbed_start": min(orphan_starts[wake_date]),
            "inbed_end": max(orphan_ends[wake_date]),
        }

    # Sum AsleepCore, AsleepDeep, AsleepREM per night (overlap with night range)
    stage_names = ("AsleepCore", "AsleepDeep", "AsleepREM")
    sums_by_night = defaultdict(lambda: {s: 0.0 for s in stage_names})

    for wake_date, rng in night_ranges.items():
        n_start = rng["inbed_start"]
        n_end = rng["inbed_end"]
        for r in rows:
            if r["value"] not in stage_names:
                continue
            # Overlap: segment overlaps night if segment.start < night_end and segment.end > night_start
            if r["start"] < n_end and r["end"] > n_start:
                sums_by_night[wake_date][r["value"]] += r["duration"]

    # Sum Awake minutes per night, and find the longest single Awake stretch.
    awake_by_night = defaultdict(float)
    out_of_bed_by_night: dict[str, dict | None] = {}
    for wake_date, rng in night_ranges.items():
        n_start = rng["inbed_start"]
        n_end = rng["inbed_end"]
        longest_awake = None
        for r in rows:
            if r["value"] != "Awake":
                continue
            if r["start"] < n_end and r["end"] > n_start:
                awake_by_night[wake_date] += r["duration"]
                if longest_awake is None or r["duration"] > longest_awake["duration"]:
                    longest_awake = r
        if longest_awake and longest_awake["duration"] >= OUT_OF_BED_THRESHOLD_MIN:
            out_of_bed_by_night[wake_date] = longest_awake
        else:
            out_of_bed_by_night[wake_date] = None

    wake_dates_sorted = sorted(night_ranges.keys())
    last_7_dates = wake_dates_sorted[-args.days:] if len(wake_dates_sorted) >= args.days else wake_dates_sorted

    last7_data = []
    for wd in last_7_dates:
        rng = night_ranges[wd]
        deep_min = sums_by_night[wd]["AsleepDeep"]
        core_min = sums_by_night[wd]["AsleepCore"]
        rem_min = sums_by_night[wd]["AsleepREM"]
        total_sleep_min = deep_min + core_min + rem_min
        deep_pct = int(round((deep_min * 100.0 / total_sleep_min))) if total_sleep_min > 0 else 0
        core_pct = int(round((core_min * 100.0 / total_sleep_min))) if total_sleep_min > 0 else 0
        rem_pct = int(round((rem_min * 100.0 / total_sleep_min))) if total_sleep_min > 0 else 0
        oob = out_of_bed_by_night.get(wd)
        if oob:
            oob_start = oob["start"].astimezone()
            oob_end = oob["end"].astimezone()
            oob_str = f"{minutes_to_hhmm(oob['duration'])} ({oob_start.strftime('%H:%M')} - {oob_end.strftime('%H:%M')})"
        else:
            oob_str = "NA"

        last7_data.append({
            "weekday": datetime.fromisoformat(wd).strftime("%a"),
            "fell_asleep": rng["inbed_start"].astimezone().strftime("%H:%M"),
            "woke_up": rng["inbed_end"].astimezone().strftime("%H:%M"),
            "awake_hhmm": minutes_to_hhmm(awake_by_night[wd]),
            "out_of_bed": oob_str,
            "total_sleep_hhmm": minutes_to_hhmm(total_sleep_min),
            "deep_hhmm_pct": f'{minutes_to_hhmm(deep_min)} ({deep_pct}%)',
            "core_hhmm_pct": f'{minutes_to_hhmm(core_min)} ({core_pct}%)',
            "rem_hhmm_pct": f'{minutes_to_hhmm(rem_min)} ({rem_pct}%)',
        })

    last_7_path = ANALYSIS_DIR / "sleep_last_7_days.csv"
    last_7_path.parent.mkdir(parents=True, exist_ok=True)
    with open(last_7_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Metric"] + [d["weekday"] for d in last7_data])
        writer.writerow(["Time fell asleep"] + [d["fell_asleep"] for d in last7_data])
        writer.writerow(["Time woke up"] + [d["woke_up"] for d in last7_data])
        writer.writerow(["Awake during night (hh:mm)"] + [d["awake_hhmm"] for d in last7_data])
        writer.writerow(["Out of bed"] + [d["out_of_bed"] for d in last7_data])
        writer.writerow(["Deep sleep (hh:mm)"] + [d["deep_hhmm_pct"] for d in last7_data])
        writer.writerow(["Core sleep (hh:mm)"] + [d["core_hhmm_pct"] for d in last7_data])
        writer.writerow(["REM sleep (hh:mm)"] + [d["rem_hhmm_pct"] for d in last7_data])
        writer.writerow(["Total sleep (hh:mm)"] + [d["total_sleep_hhmm"] for d in last7_data])
    print(f"Wrote last {len(last7_data)} nights to {last_7_path}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
