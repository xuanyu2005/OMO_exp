from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED_COLUMNS = {
    "repo",
    "instance_id",
    "base_commit",
    "patch",
    "test_patch",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
}


def run_command(args: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return 127, ""
    return result.returncode, (result.stdout or result.stderr).strip()


def check_command(name: str, args: list[str]) -> bool:
    path = shutil.which(args[0])
    if not path:
        print(f"[FAIL] {name}: command not found ({args[0]})")
        return False
    code, output = run_command(args)
    if code != 0:
        print(f"[FAIL] {name}: exit {code}")
        if output:
            print(f"       {output.splitlines()[0]}")
        return False
    first_line = output.splitlines()[0] if output else path
    print(f"[ OK ] {name}: {first_line}")
    return True


def check_import(module: str) -> bool:
    if importlib.util.find_spec(module) is None:
        print(f"[FAIL] import {module}: not installed")
        return False
    print(f"[ OK ] import {module}")
    return True


def check_harness_entrypoint() -> bool:
    if os.name == "nt":
        code = (
            "try:\n"
            "    import swebench.harness.run_evaluation\n"
            "except ModuleNotFoundError as exc:\n"
            "    if exc.name == 'resource':\n"
            "        print('windows_resource_missing')\n"
            "    else:\n"
            "        raise\n"
            "else:\n"
            "    print('ok')\n"
        )
        _, output = run_command([sys.executable, "-c", code])
        if "windows_resource_missing" in output:
            print(
                "[WARN] SWE-bench harness entrypoint: Windows native Python cannot "
                "import Unix-only module 'resource'. Run official evaluation in WSL/Linux."
            )
            return True

    code, output = run_command(
        [sys.executable, "-c", "import swebench.harness.run_evaluation; print('ok')"]
    )
    if code != 0:
        print("[FAIL] SWE-bench harness entrypoint: import failed")
        if output:
            print(f"       {output.splitlines()[-1]}")
        return False
    print("[ OK ] SWE-bench harness entrypoint")
    return True


def load_jsonl(path: Path) -> list[dict]:
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


def check_dataset(dataset_path: Path, expected_rows: int | None) -> bool:
    if not dataset_path.exists():
        print(f"[FAIL] dataset JSONL: missing {dataset_path}")
        return False

    rows = load_jsonl(dataset_path)
    print(f"[ OK ] dataset JSONL: {dataset_path} ({len(rows)} rows)")

    if expected_rows is not None and len(rows) != expected_rows:
        print(f"[FAIL] dataset row count: expected {expected_rows}, got {len(rows)}")
        return False

    if not rows:
        print("[FAIL] dataset rows: empty")
        return False

    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        print(f"[FAIL] dataset columns: missing {sorted(missing)}")
        return False

    repos: dict[str, int] = {}
    for row in rows:
        repos[row["repo"]] = repos.get(row["repo"], 0) + 1

    sample = rows[0]
    print(f"[ OK ] dataset repos: {repos}")
    print(
        "[ OK ] first instance: "
        f"{sample['instance_id']} ({sample['repo']} @ {sample['base_commit'][:12]})"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check local UV/SWE-bench prerequisites for the OMO experiment."
    )
    parser.add_argument(
        "--dataset-jsonl",
        default="experiments/data/swe-bench-verified-mini/test.jsonl",
        type=Path,
        help="Local SWE-bench Verified Mini JSONL path.",
    )
    parser.add_argument(
        "--expected-rows",
        default=50,
        type=int,
        help="Expected row count for the local mini dataset. Use -1 to skip.",
    )
    args = parser.parse_args()

    checks = [
        check_command("uv", ["uv", "--version"]),
        check_command("docker", ["docker", "--version"]),
        check_command("docker daemon", ["docker", "info", "--format", "{{json .ServerVersion}}"]),
        check_import("swebench"),
        check_harness_entrypoint(),
        check_dataset(args.dataset_jsonl, None if args.expected_rows < 0 else args.expected_rows),
    ]

    if all(checks):
        print("\nEnvironment check passed.")
        return 0

    print("\nEnvironment check failed. Fix the failed item(s) before running evaluation.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
