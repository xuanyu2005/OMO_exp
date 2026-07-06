from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create SWE-bench prediction JSONL from local gold patches. "
            "Use this only to smoke-test the harness."
        )
    )
    parser.add_argument(
        "--dataset-jsonl",
        default="experiments/data/swe-bench-verified-mini/test.jsonl",
        type=Path,
        help="Local SWE-bench Verified Mini JSONL path.",
    )
    parser.add_argument(
        "--output",
        default="experiments/results/predictions/gold_smoke.jsonl",
        type=Path,
        help="Output prediction JSONL path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Number of rows to convert from the start of the dataset.",
    )
    parser.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Specific instance id to include. Can be passed multiple times.",
    )
    parser.add_argument(
        "--model-name",
        default="gold",
        help="Value for model_name_or_path in the prediction file.",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.dataset_jsonl)
    if args.instance_id:
        wanted = set(args.instance_id)
        selected = [row for row in rows if row.get("instance_id") in wanted]
        missing = wanted - {row.get("instance_id") for row in selected}
        if missing:
            raise SystemExit(f"Missing instance id(s): {', '.join(sorted(missing))}")
    else:
        selected = rows[: args.limit]

    predictions = [
        {
            "instance_id": row["instance_id"],
            "model_name_or_path": args.model_name,
            "model_patch": row["patch"],
        }
        for row in selected
    ]
    write_jsonl(args.output, predictions)

    print(f"Wrote {len(predictions)} prediction(s) to {args.output}")
    for row in selected:
        print(f"- {row['instance_id']} ({row['repo']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
