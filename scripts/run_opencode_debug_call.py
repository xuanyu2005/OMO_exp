from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


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


def parse_usage_from_json_events(text: str) -> dict[str, int | float | None]:
    usage = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
    }

    def visit(value: object) -> None:
        if isinstance(value, dict):
            tokens = value.get("tokens")
            if isinstance(tokens, dict):
                if isinstance(tokens.get("input"), int):
                    usage["input_tokens"] = tokens["input"]
                if isinstance(tokens.get("output"), int):
                    usage["output_tokens"] = tokens["output"]
                if isinstance(tokens.get("total"), int):
                    usage["total_tokens"] = tokens["total"]
            cost = value.get("cost")
            if isinstance(cost, (int, float)):
                usage["cost_usd"] = float(cost)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        visit(event)
        blob = json.dumps(event)
        numbers = {}
        for key in ("inputTokens", "promptTokens", "input_tokens", "prompt_tokens"):
            match = re.search(rf'"{key}"\s*:\s*(\d+)', blob)
            if match:
                numbers["input_tokens"] = int(match.group(1))
                break
        for key in ("outputTokens", "completionTokens", "output_tokens", "completion_tokens"):
            match = re.search(rf'"{key}"\s*:\s*(\d+)', blob)
            if match:
                numbers["output_tokens"] = int(match.group(1))
                break
        for key in ("totalTokens", "total_tokens"):
            match = re.search(rf'"{key}"\s*:\s*(\d+)', blob)
            if match:
                numbers["total_tokens"] = int(match.group(1))
                break
        usage.update(numbers)
    if usage["total_tokens"] is None and usage["input_tokens"] is not None and usage["output_tokens"] is not None:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def find_opencode() -> str:
    for name in ("opencode.cmd", "opencode.exe", "opencode"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit("Could not find opencode executable on PATH")


def run_command(
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
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        else:
            process.kill()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return subprocess.CompletedProcess(
            command,
            124,
            stdout,
            ((stderr or "") + f"\nTIMEOUT after {timeout} seconds").strip(),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a minimal OpenCode debug call and record metrics.")
    parser.add_argument("--group", required=True, choices=["baseline", "omo"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--env-file", default=".env.siliconflow", type=Path)
    parser.add_argument("--config", default="experiments/configs/debug-siliconflow/opencode.jsonc", type=Path)
    parser.add_argument("--stage", default="debug-siliconflow")
    parser.add_argument("--provider", default="siliconflow")
    parser.add_argument("--provider-name", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--model-env", default="SILICONFLOW_MODEL")
    parser.add_argument("--agent", default="")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--base-url-env", default="SILICONFLOW_BASE_URL")
    parser.add_argument("--api-key-env", default="SILICONFLOW_API_KEY")
    parser.add_argument("--price-input-per-1m", type=float, default=None)
    parser.add_argument("--price-output-per-1m", type=float, default=None)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output-dir", default="experiments/results/runs/debug-siliconflow", type=Path)
    parser.add_argument("--metrics", default="experiments/results/runs/metrics.jsonl", type=Path)
    parser.add_argument("--api-metrics", default="experiments/results/api_metrics/api_call_metrics.jsonl", type=Path)
    args = parser.parse_args()

    env_values = load_env(args.env_file)
    base_url = env_values.get(args.base_url_env, "")
    api_key = env_values.get(args.api_key_env, "")
    model = args.model or env_values.get(args.model_env, "")
    provider_name = args.provider_name or args.provider
    if not base_url:
        raise SystemExit(f"{args.base_url_env} is empty in {args.env_file}")
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is empty in {args.env_file}")
    if not model:
        raise SystemExit(f"Model is empty. Pass --model or set {args.model_env} in {args.env_file}")

    output_dir = args.output_dir / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(env_values)
    env[args.base_url_env] = base_url
    env[args.api_key_env] = api_key
    env["OPENCODE_CONFIG"] = str(args.config.resolve())

    command = [
        find_opencode(),
        "run",
        "--format",
        "json",
        "--model",
        f"{args.provider}/{model}",
        "--title",
        args.run_id,
    ]
    if args.agent:
        command.extend(["--agent", args.agent])
    if args.auto:
        command.append("--auto")
    if args.group == "baseline":
        command.append("--pure")
    command.append(args.prompt)

    started = time.time()
    result = run_command(command, cwd=Path.cwd(), env=env, timeout=args.timeout)
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
        ),
        encoding="utf-8",
    )

    usage = parse_usage_from_json_events(stdout)
    cost_usd = usage["cost_usd"]
    if (
        cost_usd is None
        and usage["input_tokens"] is not None
        and usage["output_tokens"] is not None
        and args.price_input_per_1m is not None
        and args.price_output_per_1m is not None
    ):
        cost_usd = (
            usage["input_tokens"] / 1_000_000 * args.price_input_per_1m
            + usage["output_tokens"] / 1_000_000 * args.price_output_per_1m
        )
    row = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_id": args.run_id,
        "stage": args.stage,
        "group": args.group,
        "instance_id": "model-call-smoke",
        "provider": args.provider,
        "provider_name": provider_name,
        "model": model,
        "harness": "OpenCode" if args.group == "baseline" else "OpenCode + OMO plugin enabled",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ended)),
        "latency_ms": round((ended - started) * 1000, 3),
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "cost_usd": cost_usd,
        "price_input_per_1m": args.price_input_per_1m,
        "price_output_per_1m": args.price_output_per_1m,
        "returncode": result.returncode,
        "stdout_path": str(output_dir / "stdout.jsonl"),
        "stderr_path": str(output_dir / "stderr.txt"),
        "resolved": None,
        "notes": "Minimal real OpenCode model call; not a SWE-bench patch-generation run.",
    }
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    with args.metrics.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    args.api_metrics.parent.mkdir(parents=True, exist_ok=True)
    with args.api_metrics.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps({k: v for k, v in row.items() if k not in {"stdout_path", "stderr_path"}}, ensure_ascii=False, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
