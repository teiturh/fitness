#!/usr/bin/env python3
"""
extract_data.py
---------------
Parse Apple Health export.xml in a single streaming pass and write
all intermediate CSVs consumed by the summary scripts.

Outputs:
  - data/sleep_data.csv                     (for sleep_night_summary.py)
  - data/exercise_workouts.csv              (for workout_last_7_days_summary.py)
  - data/exercise_workout_statistics.csv    (for workout_last_7_days_summary.py)

Usage:
  python3 extract_data.py
  python3 extract_data.py --input data/export.xml --outdir data
"""

from __future__ import annotations

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


DATA_DIR = Path("data")
SLEEP_PREFIX = "HKCategoryValueSleepAnalysis"


def strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_apple_datetime(dt_str: str) -> datetime:
    if not dt_str:
        raise ValueError("Empty datetime string")
    for fmt in (
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError as e:
        raise ValueError(f"Unrecognised datetime: {dt_str!r}") from e


def to_minutes(duration: float, unit: str) -> float:
    u = (unit or "").strip().lower()
    if u in ("min", "minute", "minutes"):
        return duration
    if u in ("s", "sec", "second", "seconds"):
        return duration / 60.0
    if u in ("h", "hr", "hour", "hours"):
        return duration * 60.0
    raise ValueError(f"Unknown durationUnit: {unit!r}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Extract Apple Health data from export.xml")
    parser.add_argument("--input", type=Path, default=DATA_DIR / "export.xml")
    parser.add_argument("--outdir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)

    input_file: Path = args.input
    outdir: Path = args.outdir

    if not input_file.exists():
        print(f"Error: {input_file} not found", file=sys.stderr)
        sys.exit(1)

    outdir.mkdir(parents=True, exist_ok=True)

    sleep_csv = outdir / "sleep_data.csv"
    workouts_csv = outdir / "exercise_workouts.csv"
    stats_csv = outdir / "exercise_workout_statistics.csv"

    sleep_written = 0
    sleep_skipped = 0
    workouts_written = 0

    # Stack for tracking the current open <Workout> element and its id.
    workout_stack: list[dict[str, Any]] = []
    workout_id_counter = 0

    with (
        sleep_csv.open("w", newline="", encoding="utf-8") as sf,
        workouts_csv.open("w", newline="", encoding="utf-8") as wf,
        stats_csv.open("w", newline="", encoding="utf-8") as stf,
    ):
        sleep_writer = csv.writer(sf)
        workouts_writer = csv.writer(wf)
        stats_writer = csv.writer(stf)

        sleep_writer.writerow(["StartDate", "EndDate", "DurationMinutes", "Value"])
        workouts_writer.writerow(
            ["workout_id", "workout_activity_type", "startDate", "endDate", "durationMinutes"]
        )
        stats_writer.writerow(
            [
                "workout_id",
                "workout_activity_type",
                "stat_type",
                "stat_startDate",
                "stat_endDate",
                "sum",
                "average",
                "minimum",
                "maximum",
                "unit",
            ]
        )

        for evt, elem in ET.iterparse(str(input_file), events=("start", "end")):
            tag = strip_ns(elem.tag)

            # ── Sleep records ──────────────────────────────────────────────
            if evt == "end" and tag == "Record":
                if not workout_stack and elem.attrib.get("type", "").endswith("SleepAnalysis"):
                    try:
                        start = parse_apple_datetime(elem.attrib["startDate"])
                        end = parse_apple_datetime(elem.attrib["endDate"])
                        # Apple Health sometimes stores timestamps with a stale UTC offset
                        # (e.g. summer +02:00 in winter months). Converting to the system's
                        # local timezone gives the wall-clock time the user actually saw,
                        # with the correct DST-aware offset.
                        start = start.astimezone()
                        end = end.astimezone()
                        duration_min = (end - start).total_seconds() / 60
                        value = elem.attrib.get("value", "").replace(SLEEP_PREFIX, "").lstrip()
                        sleep_writer.writerow([
                            start.isoformat(),
                            end.isoformat(),
                            round(duration_min, 2),
                            value,
                        ])
                        sleep_written += 1
                    except (KeyError, ValueError):
                        sleep_skipped += 1
                elem.clear()
                continue

            # ── Workout open ───────────────────────────────────────────────
            if evt == "start" and tag == "Workout":
                workout_id_counter += 1
                workout_stack.append({
                    "workout_id": workout_id_counter,
                    "attrs": dict(elem.attrib),
                })
                continue

            # ── WorkoutStatistics ──────────────────────────────────────────
            if evt == "end" and tag == "WorkoutStatistics":
                if workout_stack:
                    current = workout_stack[-1]
                    stats_writer.writerow([
                        current["workout_id"],
                        current["attrs"].get("workoutActivityType", ""),
                        elem.attrib.get("type", ""),
                        elem.attrib.get("startDate", ""),
                        elem.attrib.get("endDate", ""),
                        elem.attrib.get("sum", ""),
                        elem.attrib.get("average", ""),
                        elem.attrib.get("minimum", ""),
                        elem.attrib.get("maximum", ""),
                        elem.attrib.get("unit", ""),
                    ])
                elem.clear()
                continue

            # ── Workout close ──────────────────────────────────────────────
            if evt == "end" and tag == "Workout":
                if workout_stack:
                    current = workout_stack.pop()
                    attrs = current["attrs"]

                    start_dt: Optional[datetime] = None
                    end_dt: Optional[datetime] = None
                    try:
                        start_dt = parse_apple_datetime(attrs.get("startDate", ""))
                    except ValueError:
                        pass
                    try:
                        end_dt = parse_apple_datetime(attrs.get("endDate", ""))
                    except ValueError:
                        pass

                    duration_minutes: Optional[float] = None
                    if attrs.get("duration") and attrs.get("durationUnit"):
                        try:
                            duration_minutes = to_minutes(float(attrs["duration"]), attrs["durationUnit"])
                        except ValueError:
                            pass
                    if duration_minutes is None and start_dt and end_dt:
                        duration_minutes = (end_dt - start_dt).total_seconds() / 60.0

                    workouts_writer.writerow([
                        current["workout_id"],
                        attrs.get("workoutActivityType", ""),
                        start_dt.isoformat() if start_dt else "",
                        end_dt.isoformat() if end_dt else "",
                        f"{duration_minutes:.6f}" if duration_minutes is not None else "",
                    ])
                    workouts_written += 1
                elem.clear()
                continue

            # ── Drop all other children of an open Workout ─────────────────
            if evt == "end" and workout_stack:
                elem.clear()

    print(f"Wrote {sleep_written} sleep records to {sleep_csv}", file=sys.stderr)
    if sleep_skipped:
        print(f"Skipped {sleep_skipped} sleep records", file=sys.stderr)
    print(f"Wrote {workouts_written} workouts to {workouts_csv}", file=sys.stderr)
    print(f"Wrote workout statistics to {stats_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
