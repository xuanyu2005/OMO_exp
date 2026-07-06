from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a SWE-bench prediction JSONL row from a saved git diff patch."
    )
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--patch-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-name", required=True)
    args = parser.parse_args()

    patch = args.patch_file.read_text(encoding="utf-8")
    if not patch.strip():
        raise SystemExit(f"Patch file is empty: {args.patch_file}")

    row = {
        "instance_id": args.instance_id,
        "model_name_or_path": args.model_name,
        "model_patch": patch,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote prediction for {args.instance_id} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
