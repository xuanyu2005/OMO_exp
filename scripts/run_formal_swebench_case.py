from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def run(command: list[str], *, cwd: Path, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def start_proxy(args: argparse.Namespace, log_dir: Path) -> subprocess.Popen[str]:
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / "proxy.stdout.txt").open("w", encoding="utf-8", newline="\n")
    stderr = (log_dir / "proxy.stderr.txt").open("w", encoding="utf-8", newline="\n")
    command = [
        sys.executable,
        "scripts/formal_api_compat_proxy.py",
        "--env-file",
        str(args.env_file),
        "--base-url-env",
        args.base_url_env,
        "--api-key-env",
        args.api_key_env,
        "--host",
        args.proxy_host,
        "--port",
        str(args.proxy_port),
        "--log-dir",
        str(log_dir),
        "--upstream-timeout",
        str(args.proxy_upstream_timeout),
        "--price-input-per-1m",
        str(args.price_input_per_1m),
        "--price-cache-creation-input-per-1m",
        str(args.price_cache_creation_input_per_1m),
        "--price-cached-input-per-1m",
        str(args.price_cached_input_per_1m),
        "--price-output-per-1m",
        str(args.price_output_per_1m),
    ]
    if args.price_map:
        command.extend(["--price-map", str(args.price_map)])
    if args.model_routes:
        command.extend(["--model-routes", str(args.model_routes)])
    (log_dir / "proxy_command.json").write_text(
        json.dumps({"command": command}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return subprocess.Popen(
        command,
        cwd=Path.cwd(),
        stdout=stdout,
        stderr=stderr,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def write_port_scoped_config(args: argparse.Namespace, run_id: str, log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    text = args.config.read_text(encoding="utf-8")
    data = json.loads(text)
    proxy_provider = args.proxy_config_provider or args.provider
    provider = data.setdefault("provider", {}).setdefault(proxy_provider, {})
    options = provider.setdefault("options", {})
    options["baseURL"] = f"http://{args.proxy_host}:{args.proxy_port}"
    options["apiKey"] = "formal-compat-proxy-local"
    scoped_config = log_dir / "opencode-config.jsonc"
    scoped_config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return scoped_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one formal API SWE-bench case with compatibility proxy and metrics.")
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--groups", nargs="+", choices=["baseline", "omo"], default=["baseline"])
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
    parser.add_argument("--opencode-timeout", default=1800, type=int)
    parser.add_argument("--harness-timeout", default=2400, type=int)
    parser.add_argument("--harness-retries", default=2, type=int)
    parser.add_argument("--harness-retry-sleep", default=20, type=int)
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", default=18082, type=int)
    parser.add_argument("--proxy-upstream-timeout", default=2400, type=int)
    parser.add_argument("--proxy-log-root", default="experiments/results/runs/formal-gpt-compat", type=Path)
    parser.add_argument("--no-proxy", action="store_true", help="Use the config directly without starting the compatibility proxy.")
    parser.add_argument("--metrics", default="experiments/results/runs/metrics.jsonl", type=Path)
    parser.add_argument("--api-metrics", default="experiments/results/api_metrics/api_call_metrics.jsonl", type=Path)
    parser.add_argument("--api-metrics-summary", default="experiments/results/api_metrics/api_call_metrics_summary.md", type=Path)
    parser.add_argument(
        "--omo-config",
        default=None,
        type=Path,
        help="Optional project-local OMO config template to install only for this run.",
    )
    args = parser.parse_args()
    if len(args.groups) != 1:
        raise SystemExit("Run one group per invocation so proxy usage/cost can be attributed to one run_id.")
    if args.price_cache_creation_input_per_1m is None:
        args.price_cache_creation_input_per_1m = args.price_input_per_1m

    run_ids = [f"{args.stage}-{args.generation_mode}-{group}-{args.instance_id}" for group in args.groups]
    proxy_log_dir = args.proxy_log_root / f"compat-proxy-{run_ids[0]}"
    if args.no_proxy:
        scoped_config = args.config
        proxy = None
    else:
        proxy_log_dir.mkdir(parents=True, exist_ok=True)
        for stale_name in ("requests.jsonl", "proxy_metrics_summary.json", "proxy.stdout.txt", "proxy.stderr.txt"):
            stale_path = proxy_log_dir / stale_name
            if stale_path.exists():
                stale_path.unlink()
        scoped_config = write_port_scoped_config(args, run_ids[0], proxy_log_dir)
        proxy = start_proxy(args, proxy_log_dir)
    try:
        if proxy is not None:
            time.sleep(2)
            if proxy.poll() is not None:
                raise SystemExit(f"Compatibility proxy exited early with code {proxy.returncode}; see {proxy_log_dir}")

        pilot_command = [
            sys.executable,
            "scripts/run_swebench_pilot.py",
            "--instance-id",
            args.instance_id,
            "--groups",
            *args.groups,
            "--dataset-jsonl",
            str(args.dataset_jsonl),
            "--env-file",
            str(args.env_file),
            "--config",
            str(scoped_config),
            "--stage",
            args.stage,
            "--provider",
            args.provider,
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
            "--price-cache-creation-input-per-1m",
            str(args.price_cache_creation_input_per_1m),
            "--price-cached-input-per-1m",
            str(args.price_cached_input_per_1m),
            "--price-output-per-1m",
            str(args.price_output_per_1m),
            "--workspace-root",
            str(args.workspace_root),
            "--result-root",
            str(args.result_root),
            "--metrics",
            str(args.metrics),
            "--api-metrics",
            str(args.api_metrics),
            "--generation-mode",
            args.generation_mode,
            "--opencode-timeout",
            str(args.opencode_timeout),
            "--harness-timeout",
            str(args.harness_timeout),
            "--harness-retries",
            str(args.harness_retries),
            "--harness-retry-sleep",
            str(args.harness_retry_sleep),
        ]
        if args.agent:
            pilot_command.extend(["--agent", args.agent])
        if args.omo_config:
            pilot_command.extend(["--omo-config", str(args.omo_config)])
        if args.allow_subagents:
            pilot_command.append("--allow-subagents")
        if args.require_subagent_delegation:
            pilot_command.append("--require-subagent-delegation")
        if args.subagent_policy:
            pilot_command.extend(["--subagent-policy", args.subagent_policy])
        pilot = run(pilot_command, cwd=Path.cwd())
        if pilot.returncode != 0:
            return pilot.returncode

        if proxy is not None:
            proxy_requests = proxy_log_dir / "requests.jsonl"
            proxy_summary = proxy_log_dir / "proxy_metrics_summary.json"
            if not proxy_requests.exists():
                proxy_summary.write_text(
                    json.dumps(
                        {
                            "request_count": 0,
                            "successful_request_count": 0,
                            "input_tokens": 0,
                            "base_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                            "cached_input_tokens": 0,
                            "billable_input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                            "latency_ms_sum": 0.0,
                            "price_input_per_1m": args.price_input_per_1m,
                            "price_cache_creation_input_per_1m": args.price_cache_creation_input_per_1m,
                            "price_cached_input_per_1m": args.price_cached_input_per_1m,
                            "price_output_per_1m": args.price_output_per_1m,
                            "cost_usd": 0.0,
                            "model_costs": {},
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(f"No compatibility proxy requests captured for {run_ids[0]}; keeping direct-provider metrics.")
            else:
                summary_command = [
                    sys.executable,
                    "scripts/summarize_formal_proxy_metrics.py",
                    str(proxy_requests),
                    "--output",
                    str(proxy_summary),
                    "--price-input-per-1m",
                    str(args.price_input_per_1m),
                    "--price-cache-creation-input-per-1m",
                    str(args.price_cache_creation_input_per_1m),
                    "--price-cached-input-per-1m",
                    str(args.price_cached_input_per_1m),
                    "--price-output-per-1m",
                    str(args.price_output_per_1m),
                ]
                if args.price_map:
                    summary_command.extend(["--price-map", str(args.price_map)])
                summary = run(summary_command, cwd=Path.cwd())
                if summary.returncode != 0:
                    return summary.returncode

                for run_id in run_ids:
                    apply_metrics = run(
                        [
                            sys.executable,
                            "scripts/apply_proxy_metrics_to_run.py",
                            "--metrics",
                            str(args.metrics),
                            "--run-id",
                            run_id,
                            "--proxy-summary",
                            str(proxy_summary),
                        ],
                        cwd=Path.cwd(),
                    )
                    if apply_metrics.returncode != 0:
                        return apply_metrics.returncode

        sync = run(
            [
                sys.executable,
                "scripts/sync_api_metrics_log.py",
                "--source",
                str(args.metrics),
                "--output",
                str(args.api_metrics),
                "--summary",
                str(args.api_metrics_summary),
            ],
            cwd=Path.cwd(),
        )
        if sync.returncode != 0:
            return sync.returncode
    finally:
        if proxy is not None:
            stop_process(proxy)

    print(
        json.dumps(
            {"run_ids": run_ids, "proxy_log_dir": "" if args.no_proxy else str(proxy_log_dir), "no_proxy": args.no_proxy},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
