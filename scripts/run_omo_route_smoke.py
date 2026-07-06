from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from run_formal_swebench_case import start_proxy, stop_process, write_port_scoped_config


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
]


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(0).split()[0] + " REDACTED" if " " in m.group(0) else "sk-REDACTED", text)
    return text


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise SystemExit(f"Missing env file: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def find_opencode() -> str:
    for name in ("opencode.cmd", "opencode.exe", "opencode"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit("Could not find opencode executable on PATH")


def install_isolated_omo_config(cwd: Path, config_path: Path) -> None:
    target_dir = cwd / ".opencode"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "oh-my-openagent.jsonc").write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")


def run_opencode(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            process.kill()
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(
            command,
            124,
            stdout,
            ((stderr or "") + f"\nTIMEOUT after {timeout} seconds").strip(),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test OMO subagent routing without running SWE-bench harness.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--provider", default="formal-claude-anthropic")
    parser.add_argument("--proxy-config-provider", default="formal-gpt-compat-proxy")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--agent", default="Sisyphus - ultraworker")
    parser.add_argument("--omo-config", required=True, type=Path)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--timeout", default=900, type=int)
    parser.add_argument("--output-root", default="experiments/results/runs/omo-route-smoke", type=Path)
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", default=18082, type=int)
    parser.add_argument("--proxy-upstream-timeout", default=900, type=int)
    parser.add_argument("--base-url-env", default="GPT_BASE_URL")
    parser.add_argument("--api-key-env", default="GPT_API_KEY")
    parser.add_argument("--price-input-per-1m", default=2.5, type=float)
    parser.add_argument("--price-cache-creation-input-per-1m", default=None, type=float)
    parser.add_argument("--price-cached-input-per-1m", default=0.25, type=float)
    parser.add_argument("--price-output-per-1m", default=15.0, type=float)
    parser.add_argument("--price-map", default=None, type=Path)
    parser.add_argument("--model-routes", default=None, type=Path)
    args = parser.parse_args()
    if args.price_cache_creation_input_per_1m is None:
        args.price_cache_creation_input_per_1m = args.price_input_per_1m

    output_dir = args.output_root / args.run_id
    proxy_log_dir = output_dir / "proxy"
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_name in ("requests.jsonl", "proxy_metrics_summary.json", "proxy.stdout.txt", "proxy.stderr.txt"):
        stale_path = proxy_log_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()

    scoped_config = write_port_scoped_config(args, args.run_id, proxy_log_dir)
    proxy = start_proxy(args, proxy_log_dir)
    isolated_cwd = output_dir / "opencode-cwd"
    isolated_cwd.mkdir(parents=True, exist_ok=True)
    install_isolated_omo_config(isolated_cwd, args.omo_config)
    started = time.time()
    try:
        time.sleep(2)
        if proxy.poll() is not None:
            raise SystemExit(f"Compatibility proxy exited early with code {proxy.returncode}; see {proxy_log_dir}")

        env = os.environ.copy()
        env.update(load_env(args.env_file))
        env["OPENCODE_CONFIG"] = str(scoped_config.resolve())
        prompt = args.prompt or (
            "Use the task tool exactly once with category=\"deep\". Ask the subagent to answer only: "
            "\"OMO route smoke OK\". After the subagent returns, reply with one sentence naming the result. "
            "Do not edit files."
        )
        command = [
            find_opencode(),
            "run",
            "--format",
            "json",
            "--model",
            f"{args.provider}/{args.model}",
            "--title",
            args.run_id,
            "--agent",
            args.agent,
            "--auto",
            "--log-level",
            "ERROR",
            prompt,
        ]
        result = run_opencode(command, cwd=isolated_cwd, env=env, timeout=args.timeout)
        ended = time.time()
        stdout = redact(result.stdout or "")
        stderr = redact(result.stderr or "")
        (output_dir / "stdout.jsonl").write_text(stdout, encoding="utf-8")
        (output_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        (output_dir / "command.json").write_text(
            json.dumps(
                {
                    "command": command,
                    "returncode": result.returncode,
                    "started_at_epoch": started,
                    "ended_at_epoch": ended,
                    "latency_ms": round((ended - started) * 1000, 3),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        requests_path = proxy_log_dir / "requests.jsonl"
        request_rows = []
        if requests_path.exists():
            request_rows = [json.loads(line) for line in requests_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        models = []
        for row in request_rows:
            request = row.get("request")
            if isinstance(request, dict):
                models.append(request.get("model"))
        summary = {
            "run_id": args.run_id,
            "returncode": result.returncode,
            "proxy_request_count": len(request_rows),
            "proxy_models": models,
            "saw_gpt_5_4": "gpt-5.4" in models,
            "stdout_path": str(output_dir / "stdout.jsonl"),
            "stderr_path": str(output_dir / "stderr.txt"),
            "proxy_log_dir": str(proxy_log_dir),
        }
        (output_dir / "route_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if result.returncode == 0 and summary["saw_gpt_5_4"] else 1
    finally:
        stop_process(proxy)


if __name__ == "__main__":
    raise SystemExit(main())
