#!/usr/bin/env python3
"""
extract_sleep_data_simple.py
----------------------------
Parse Apple Health export.xml and write sleep records to sleep_data.csv
without the Source column, and with simplified Value labels.

Usage:
    python3 extract_sleep_data_simple.py
"""

import xml.etree.ElementTree as ET
import csv
from datetime import datetime
from pathlib import Path

# ── CONFIG ───────────────────────────────────────────────────────────
INPUT_FILE  = Path("export.xml")          # Edit if your xml is elsewhere
OUTPUT_FILE = Path("sleep_data.csv")
PREFIX      = "HKCategoryValueSleepAnalysis"
# ──────────────────────────────────────────────────────────────────────


def parse_apple_datetime(dt_str: str) -> datetime:
    """Parses Apple-style datetime strings."""
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised datetime: {dt_str}")


def simplify_value(value: str) -> str:
    """Remove the long HKCategoryValueSleepAnalysis prefix, if present."""
    return value.replace(PREFIX, "").lstrip()


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"{INPUT_FILE} not found. "
            "Move the script to the folder with export.xml or adjust INPUT_FILE."
        )

    print("🔍 Parsing export.xml …")
    tree = ET.parse(INPUT_FILE)
    root = tree.getroot()

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["StartDate", "EndDate", "DurationMinutes", "Value"])

        skipped = 0
        written = 0

        for record in root.findall("Record"):
            if not record.attrib.get("type", "").endswith("SleepAnalysis"):
                continue

            try:
                start = parse_apple_datetime(record.attrib["startDate"])
                end   = parse_apple_datetime(record.attrib["endDate"])
            except (KeyError, ValueError) as e:
                skipped += 1
                print(f"⚠️  Skipping record: {e}")
                continue

            duration_min = (end - start).total_seconds() / 60
            raw_value = record.attrib.get("value", "")
            value = simplify_value(raw_value)

            writer.writerow([
                start.isoformat(),
                end.isoformat(),
                round(duration_min, 2),
                value
            ])
            written += 1

    print(f"✅ Finished. {written} records written to {OUTPUT_FILE}")
    if skipped:
        print(f"⚠️  {skipped} records skipped due to parsing issues.")


if __name__ == "__main__":
    main()
