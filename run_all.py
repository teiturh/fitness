#!/usr/bin/env python3
"""
run_all.py
----------
Full pipeline: extract data from export.xml, then run both summary scripts.

Steps:
  1. extract_data.py        -- single XML pass → data/*.csv
  2. sleep_night_summary.py -- sleep CSV    → analysis/sleep_last_7_days_<start>_to_<end>.csv
  3. workout_summary.py -- workout CSVs → analysis/workout_summary_<start>_to_<end>.csv

Usage:
  python3 run_all.py
  python3 run_all.py --days 14
"""

from __future__ import annotations

import argparse
import sys
import time

import extract_data
import sleep_night_summary
import workout_summary


def run_step(label: str, fn, argv: list[str]) -> None:
    print(f"\n-- {label}")
    t0 = time.monotonic()
    fn(argv)
    elapsed = time.monotonic() - t0
    print(f"   done in {elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full Apple Health pipeline.")
    parser.add_argument("--days", type=int, default=7, help="Number of days to summarise (default: 7)")
    args = parser.parse_args()

    days_argv = ["--days", str(args.days)]
    t_start = time.monotonic()

    try:
        run_step("Extracting data from export.xml", extract_data.main, [])
        run_step(f"Summarising sleep (last {args.days} days)", sleep_night_summary.main, days_argv)
        run_step(f"Summarising workouts (last {args.days} days)", workout_summary.main, days_argv)
    except SystemExit as e:
        print(f"\nPipeline failed (exit code {e.code})", file=sys.stderr)
        sys.exit(e.code)
    except Exception as e:
        print(f"\nPipeline failed: {e}", file=sys.stderr)
        sys.exit(1)

    total = time.monotonic() - t_start
    print(f"\nAll done in {total:.1f}s")
    print("  analysis/sleep_last_7_days_<start>_to_<end>.csv")
    print("  analysis/workout_summary_<start>_to_<end>.csv")


if __name__ == "__main__":
    main()
