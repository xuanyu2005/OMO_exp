#!/usr/bin/env python3
"""Summarize experiment CSV results by condition."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path


def as_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def truthy(value: str) -> bool | None:
    value = (value or "").strip().lower()
    if value in {"1", "true", "yes", "y", "pass", "passed"}:
        return True
    if value in {"0", "false", "no", "n", "fail", "failed"}:
        return False
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/summarize_results.py <results.csv>")
        return 2

    path = Path(sys.argv[1])
    rows = list(csv.DictReader(path.open("r", encoding="utf-8-sig", newline="")))
    by_condition: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("condition"):
            by_condition[row["condition"]].append(row)

    print("| condition | n | success_rate | avg_quality | avg_time_sec | avg_cost_usd |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for condition, items in sorted(by_condition.items()):
        successes = [truthy(row.get("success", "")) for row in items]
        successes = [item for item in successes if item is not None]
        quality = [as_float(row.get("quality_score", "")) for row in items]
        quality = [item for item in quality if item is not None]
        times = [as_float(row.get("time_seconds", "")) for row in items]
        times = [item for item in times if item is not None]
        costs = [as_float(row.get("estimated_cost_usd", "")) for row in items]
        costs = [item for item in costs if item is not None]

        success_rate = sum(successes) / len(successes) if successes else 0.0
        avg_quality = sum(quality) / len(quality) if quality else 0.0
        avg_time = sum(times) / len(times) if times else 0.0
        avg_cost = sum(costs) / len(costs) if costs else 0.0
        print(
            f"| {condition} | {len(items)} | {success_rate:.2%} | "
            f"{avg_quality:.2f} | {avg_time:.1f} | {avg_cost:.4f} |"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

