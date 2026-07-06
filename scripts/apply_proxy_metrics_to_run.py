from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply formal API proxy usage/cost summary to run metrics rows.")
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--proxy-summary", required=True, type=Path)
    args = parser.parse_args()

    summary = json.loads(args.proxy_summary.read_text(encoding="utf-8"))
    rows = read_jsonl(args.metrics)
    updated = 0
    for row in rows:
        if row.get("run_id") != args.run_id:
            continue
        row["input_tokens"] = summary.get("input_tokens")
        row["base_input_tokens"] = summary.get("base_input_tokens")
        row["cache_creation_input_tokens"] = summary.get("cache_creation_input_tokens")
        row["cached_input_tokens"] = summary.get("cached_input_tokens")
        row["billable_input_tokens"] = summary.get("billable_input_tokens")
        row["output_tokens"] = summary.get("output_tokens")
        row["total_tokens"] = summary.get("total_tokens")
        row["cost_usd"] = summary.get("cost_usd")
        row["proxy_request_count"] = summary.get("request_count")
        row["proxy_successful_request_count"] = summary.get("successful_request_count")
        row["proxy_latency_ms_sum"] = summary.get("latency_ms_sum")
        row["price_input_per_1m"] = summary.get("price_input_per_1m")
        row["price_cache_creation_input_per_1m"] = summary.get("price_cache_creation_input_per_1m")
        row["price_cached_input_per_1m"] = summary.get("price_cached_input_per_1m")
        updated += 1
    if updated == 0:
        raise SystemExit(f"No row found for run_id={args.run_id} in {args.metrics}")
    write_jsonl(args.metrics, rows)
    print(f"Updated {updated} row(s) in {args.metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
