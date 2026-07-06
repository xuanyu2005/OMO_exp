from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def read_ids(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"Missing ids file: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def expected_report_name(provider: str, generation_mode: str, group: str, model: str, run_id: str) -> Path:
    safe_model = model.replace("/", "__").replace("\\", "__")
    return Path(f"{provider}-{generation_mode}-{group}-{safe_model}.{run_id}.json")


def is_completed(args: argparse.Namespace, instance_id: str) -> bool:
    run_id = f"{args.stage}-{args.generation_mode}-{args.group}-{instance_id}"
    output_dir = args.result_root / "runs" / args.stage / run_id
    report = expected_report_name(args.provider, args.generation_mode, args.group, args.model, run_id)
    return (
        report.exists()
        and (output_dir / "patch.diff").exists()
        and (output_dir / "harness.stdout.txt").exists()
        and (output_dir / "harness.stderr.txt").exists()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a batch of formal API SWE-bench cases for one group.")
    parser.add_argument("--group", required=True, choices=["baseline", "omo"])
    parser.add_argument("--ids-file", default="experiments/data/swe-bench-verified-mini/selected_25_balanced_ids.txt", type=Path)
    parser.add_argument("--dataset-jsonl", default="experiments/data/swe-bench-verified-mini/selected_25_balanced.jsonl", type=Path)
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--config", default="experiments/configs/formal-gpt/opencode-compat-proxy.jsonc", type=Path)
    parser.add_argument("--stage", default="formal-gpt-compat")
    parser.add_argument("--provider", default="formal-gpt-compat-proxy")
    parser.add_argument(
        "--proxy-config-provider",
        default="",
        help="Provider in the OpenCode config that should be rewritten to the local proxy. Defaults to --provider.",
    )
    parser.add_argument("--provider-name", default="Formal GPT API via compat proxy")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--agent", default="", help="Optional OpenCode agent for non-baseline/OMO runs.")
    parser.add_argument(
        "--allow-subagents",
        action="store_true",
        help="Allow task/subagent tools in the generated SWE-bench prompt.",
    )
    parser.add_argument(
        "--require-subagent-delegation",
        action="store_true",
        help="Require one deep/reviewer task/subagent before editing. Intended only for OMO multi experiments.",
    )
    parser.add_argument(
        "--subagent-policy",
        choices=["disabled", "allowed", "optional-on-uncertainty", "post-patch-review", "forced"],
        default=None,
        help=(
            "Subagent usage policy for edit-workspace prompts. Legacy --allow-subagents maps to allowed; "
            "legacy --require-subagent-delegation maps to forced."
        ),
    )
    parser.add_argument("--base-url-env", default="GPT_BASE_URL")
    parser.add_argument("--api-key-env", default="GPT_API_KEY")
    parser.add_argument("--price-input-per-1m", default=2.5, type=float)
    parser.add_argument("--price-cache-creation-input-per-1m", default=None, type=float)
    parser.add_argument("--price-cached-input-per-1m", default=0.25, type=float)
    parser.add_argument("--price-output-per-1m", default=15.0, type=float)
    parser.add_argument("--price-map", default=None, type=Path)
    parser.add_argument("--model-routes", default=None, type=Path)
    parser.add_argument("--generation-mode", choices=["edit-workspace", "diff-output"], default="edit-workspace")
    parser.add_argument("--workspace-root", default="experiments/workspaces/formal-gpt-compat", type=Path)
    parser.add_argument("--result-root", default="experiments/results", type=Path)
    parser.add_argument("--proxy-port", default=18082, type=int)
    parser.add_argument("--proxy-log-root", default="experiments/results/runs/formal-gpt-compat", type=Path)
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--opencode-timeout", default=3000, type=int)
    parser.add_argument("--harness-timeout", default=2400, type=int)
    parser.add_argument("--harness-retries", default=2, type=int)
    parser.add_argument("--harness-retry-sleep", default=20, type=int)
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--api-metrics", required=True, type=Path)
    parser.add_argument("--api-metrics-summary", required=True, type=Path)
    parser.add_argument("--batch-log-dir", required=True, type=Path)
    parser.add_argument("--status-jsonl", default=None, type=Path)
    parser.add_argument("--omo-config", default=None, type=Path)
    parser.add_argument("--rerun-completed", action="store_true")
    parser.add_argument("--limit", default=0, type=int)
    args = parser.parse_args()

    ids = read_ids(args.ids_file)
    if args.limit:
        ids = ids[: args.limit]
    args.batch_log_dir.mkdir(parents=True, exist_ok=True)
    status_jsonl = args.status_jsonl or (args.batch_log_dir / "batch_status.jsonl")

    failures = 0
    for index, instance_id in enumerate(ids, 1):
        run_id = f"{args.stage}-{args.generation_mode}-{args.group}-{instance_id}"
        if not args.rerun_completed and is_completed(args, instance_id):
            row = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "index": index,
                "instance_id": instance_id,
                "run_id": run_id,
                "group": args.group,
                "status": "skipped_completed",
            }
            print(json.dumps(row, ensure_ascii=False), flush=True)
            write_jsonl(status_jsonl, row)
            continue

        stdout_path = args.batch_log_dir / f"{run_id}.stdout.txt"
        stderr_path = args.batch_log_dir / f"{run_id}.stderr.txt"
        command = [
            sys.executable,
            "scripts/run_formal_swebench_case.py",
            "--instance-id",
            instance_id,
            "--groups",
            args.group,
            "--dataset-jsonl",
            str(args.dataset_jsonl),
            "--env-file",
            str(args.env_file),
            "--config",
            str(args.config),
            "--stage",
            args.stage,
        "--provider",
        args.provider,
        "--proxy-config-provider",
        args.proxy_config_provider,
        "--provider-name",
        args.provider_name,
            "--model",
            args.model,
            "--base-url-env",
            args.base_url_env,
            "--api-key-env",
            args.api_key_env,
            "--price-input-per-1m",
            str(args.price_input_per_1m),
            "--price-cached-input-per-1m",
            str(args.price_cached_input_per_1m),
            "--price-output-per-1m",
            str(args.price_output_per_1m),
            "--generation-mode",
            args.generation_mode,
            "--workspace-root",
            str(args.workspace_root),
            "--result-root",
            str(args.result_root),
            "--proxy-port",
            str(args.proxy_port),
            "--proxy-log-root",
            str(args.proxy_log_root),
            "--opencode-timeout",
            str(args.opencode_timeout),
            "--harness-timeout",
            str(args.harness_timeout),
            "--harness-retries",
            str(args.harness_retries),
            "--harness-retry-sleep",
            str(args.harness_retry_sleep),
            "--metrics",
            str(args.metrics),
            "--api-metrics",
            str(args.api_metrics),
            "--api-metrics-summary",
            str(args.api_metrics_summary),
        ]
        if args.price_cache_creation_input_per_1m is not None:
            command.extend(["--price-cache-creation-input-per-1m", str(args.price_cache_creation_input_per_1m)])
        if args.price_map:
            command.extend(["--price-map", str(args.price_map)])
        if args.model_routes:
            command.extend(["--model-routes", str(args.model_routes)])
        if args.no_proxy:
            command.append("--no-proxy")
        if args.omo_config:
            command.extend(["--omo-config", str(args.omo_config)])
        if args.agent:
            command.extend(["--agent", args.agent])
        if args.allow_subagents:
            command.append("--allow-subagents")
        if args.require_subagent_delegation:
            command.append("--require-subagent-delegation")
        if args.subagent_policy:
            command.extend(["--subagent-policy", args.subagent_policy])

        started = time.time()
        start_row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "index": index,
            "instance_id": instance_id,
            "run_id": run_id,
            "group": args.group,
            "status": "started",
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        }
        print(json.dumps(start_row, ensure_ascii=False), flush=True)
        write_jsonl(status_jsonl, start_row)
        with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout, stderr_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, text=True, encoding="utf-8", errors="replace")
        ended = time.time()
        end_row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "index": index,
            "instance_id": instance_id,
            "run_id": run_id,
            "group": args.group,
            "status": "completed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "duration_seconds": round(ended - started, 3),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        }
        print(json.dumps(end_row, ensure_ascii=False), flush=True)
        write_jsonl(status_jsonl, end_row)
        if result.returncode != 0:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
