from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append one OpenCode/OMO experiment metrics row as JSONL."
    )
    parser.add_argument("--output", default="experiments/results/runs/metrics.jsonl", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage", default="debug-siliconflow")
    parser.add_argument("--group", required=True, help="baseline, omo-single, or omo-multi")
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--provider", default="siliconflow")
    parser.add_argument("--model", required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--started-at", default="")
    parser.add_argument("--ended-at", default="")
    parser.add_argument("--latency-ms", type=float, default=None)
    parser.add_argument("--input-tokens", type=int, default=None)
    parser.add_argument("--output-tokens", type=int, default=None)
    parser.add_argument("--total-tokens", type=int, default=None)
    parser.add_argument("--cost-usd", type=float, default=None)
    parser.add_argument("--opencode-returncode", type=int, default=None)
    parser.add_argument("--patch-bytes", type=int, default=None)
    parser.add_argument("--harness-returncode", type=int, default=None)
    parser.add_argument("--patch-path", default="")
    parser.add_argument("--prediction-path", default="")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--resolved", choices=["true", "false", "unknown"], default="unknown")
    parser.add_argument("--notes", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    total_tokens = args.total_tokens
    if total_tokens is None and args.input_tokens is not None and args.output_tokens is not None:
        total_tokens = args.input_tokens + args.output_tokens

    row = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_id": args.run_id,
        "stage": args.stage,
        "group": args.group,
        "instance_id": args.instance_id,
        "provider": args.provider,
        "model": args.model,
        "harness": args.harness,
        "started_at": args.started_at,
        "ended_at": args.ended_at,
        "latency_ms": args.latency_ms,
        "input_tokens": args.input_tokens,
        "output_tokens": args.output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": args.cost_usd,
        "opencode_returncode": args.opencode_returncode,
        "patch_bytes": args.patch_bytes,
        "harness_returncode": args.harness_returncode,
        "patch_path": args.patch_path,
        "prediction_path": args.prediction_path,
        "report_path": args.report_path,
        "resolved": None if args.resolved == "unknown" else args.resolved == "true",
        "notes": args.notes,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Appended metrics row to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
