#!/usr/bin/env python3
"""
extract_exercise_data.py
-------------------------
Extract Apple Health workouts from export.xml for `workout_last_7_days_summary.py`.

Writes only:
  - data/exercise_workouts.csv  (workout_id, workout_activity_type, startDate, durationMinutes)
  - data/exercise_workout_statistics.csv  (<WorkoutStatistics> rows)

Usage:
  python3 extract_exercise_data.py
  python3 extract_exercise_data.py --input data/export.xml --outdir data
  python3 extract_exercise_data.py --max-workouts 50
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


def strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_apple_datetime(dt_str: str) -> datetime:
    if dt_str is None or dt_str == "":
        raise ValueError("Empty datetime string")
    formats = (
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError as e:
        raise ValueError(f"Unrecognised datetime: {dt_str!r}") from e


def to_minutes(duration: float, unit: str) -> float:
    unit_norm = (unit or "").strip().lower()
    if unit_norm in ("min", "minute", "minutes"):
        return duration
    if unit_norm in ("s", "sec", "second", "seconds"):
        return duration / 60.0
    if unit_norm in ("h", "hr", "hour", "hours"):
        return duration * 60.0
    raise ValueError(f"Unknown durationUnit: {unit!r}")


def parse_duration_minutes(duration_str: str, duration_unit: str) -> float:
    duration = float(duration_str)
    return to_minutes(duration, duration_unit)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DATA_DIR / "export.xml")
    parser.add_argument("--outdir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-workouts", type=int, default=0, help="Stop after N workouts (0 = no limit)")
    args = parser.parse_args()

    input_file: Path = args.input
    outdir: Path = args.outdir

    if not input_file.exists():
        print(f"Error: {input_file} not found", file=sys.stderr)
        sys.exit(1)

    outdir.mkdir(parents=True, exist_ok=True)
    workouts_csv = outdir / "exercise_workouts.csv"
    stats_csv = outdir / "exercise_workout_statistics.csv"

    workout_id_counter = 0
    workouts_written = 0
    workout_stack: list[dict[str, Any]] = []

    with (
        workouts_csv.open("w", newline="", encoding="utf-8") as wf,
        stats_csv.open("w", newline="", encoding="utf-8") as sf,
    ):
        workouts_writer = csv.writer(wf)
        stats_writer = csv.writer(sf)

        workouts_writer.writerow(
            ["workout_id", "workout_activity_type", "startDate", "durationMinutes"]
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

        context = ET.iterparse(str(input_file), events=("start", "end"))

        for evt, elem in context:
            tag = strip_ns(elem.tag)

            if evt == "start" and tag == "Workout":
                workout_id_counter += 1
                workout_stack.append({"workout_id": workout_id_counter, "attrs": dict(elem.attrib)})

            elif evt == "end" and tag == "WorkoutStatistics":
                if not workout_stack:
                    elem.clear()
                    continue
                current = workout_stack[-1]
                wa = current["attrs"]
                stats_writer.writerow(
                    [
                        current["workout_id"],
                        wa.get("workoutActivityType", ""),
                        elem.attrib.get("type", ""),
                        elem.attrib.get("startDate", ""),
                        elem.attrib.get("endDate", ""),
                        elem.attrib.get("sum", ""),
                        elem.attrib.get("average", ""),
                        elem.attrib.get("minimum", ""),
                        elem.attrib.get("maximum", ""),
                        elem.attrib.get("unit", ""),
                    ]
                )
                elem.clear()

            elif evt == "end" and tag == "Workout":
                if not workout_stack:
                    elem.clear()
                    continue
                current = workout_stack.pop()
                attrs = current["attrs"]
                workout_activity_type = attrs.get("workoutActivityType", "")
                start_raw = attrs.get("startDate", "")
                end_raw = attrs.get("endDate", "")
                start_dt: Optional[datetime] = None
                end_dt: Optional[datetime] = None
                if start_raw:
                    try:
                        start_dt = parse_apple_datetime(start_raw)
                    except ValueError:
                        start_dt = None
                if end_raw:
                    try:
                        end_dt = parse_apple_datetime(end_raw)
                    except ValueError:
                        end_dt = None

                duration_minutes: Optional[float] = None
                if "duration" in attrs and attrs.get("durationUnit"):
                    try:
                        duration_minutes = parse_duration_minutes(attrs["duration"], attrs["durationUnit"])
                    except ValueError:
                        duration_minutes = None
                if duration_minutes is None and start_dt and end_dt:
                    duration_minutes = (end_dt - start_dt).total_seconds() / 60.0

                workouts_writer.writerow(
                    [
                        current["workout_id"],
                        workout_activity_type,
                        start_dt.isoformat() if start_dt else "",
                        "" if duration_minutes is None else f"{duration_minutes:.6f}",
                    ]
                )
                workouts_written += 1
                elem.clear()

                if args.max_workouts and workouts_written >= args.max_workouts:
                    break

            elif evt == "end" and workout_stack:
                # Drop other <Workout> children (metadata, events, routes, …) without keeping them in memory.
                elem.clear()

    print(f"Wrote {workouts_written} workouts to {workouts_csv}", file=sys.stderr)
    print(f"Wrote workout statistics to {stats_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
