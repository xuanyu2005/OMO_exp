from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import time
import stat
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
]


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(
            lambda m: m.group(0).split()[0] + " REDACTED"
            if " " in m.group(0)
            else "sk-REDACTED",
            text,
        )
    return text


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    preexec_fn = None if os.name == "nt" else os.setsid
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        preexec_fn=preexec_fn,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args=args, returncode=process.returncode, stdout=stdout, stderr=stderr)
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
            os.killpg(process.pid, signal.SIGKILL)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=stdout,
            stderr=((stderr or "") + f"\nTIMEOUT after {timeout} seconds").strip(),
        )


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


def require_env_value(env_values: dict[str, str], name: str, env_file: Path) -> str:
    value = env_values.get(name, "")
    if not value:
        raise SystemExit(f"{name} is empty in {env_file}")
    return value


def calculate_cost_usd(
    *,
    input_tokens: int | float | None,
    output_tokens: int | float | None,
    input_price_per_1m: float | None,
    output_price_per_1m: float | None,
    base_input_tokens: int | float | None = None,
    cache_creation_input_tokens: int | float | None = None,
    cached_input_tokens: int | float | None = None,
    cache_creation_input_price_per_1m: float | None = None,
    cached_input_price_per_1m: float | None = None,
) -> float | None:
    if (
        input_tokens is None
        or output_tokens is None
        or input_price_per_1m is None
        or output_price_per_1m is None
    ):
        return None
    if base_input_tokens is not None:
        cache_creation_input_tokens = cache_creation_input_tokens or 0
        cached_input_tokens = cached_input_tokens or 0
        cache_creation_input_price_per_1m = (
            cache_creation_input_price_per_1m
            if cache_creation_input_price_per_1m is not None
            else input_price_per_1m
        )
        cached_input_price_per_1m = (
            cached_input_price_per_1m if cached_input_price_per_1m is not None else input_price_per_1m
        )
        return (
            float(base_input_tokens) / 1_000_000 * input_price_per_1m
            + float(cache_creation_input_tokens) / 1_000_000 * cache_creation_input_price_per_1m
            + float(cached_input_tokens) / 1_000_000 * cached_input_price_per_1m
            + float(output_tokens) / 1_000_000 * output_price_per_1m
        )
    return float(input_tokens) / 1_000_000 * input_price_per_1m + float(output_tokens) / 1_000_000 * output_price_per_1m


def load_instance(dataset_jsonl: Path, instance_id: str) -> dict:
    for line in dataset_jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["instance_id"] == instance_id:
            return row
    raise SystemExit(f"Instance not found: {instance_id}")


def repo_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def find_opencode() -> str:
    for name in ("opencode.cmd", "opencode.exe", "opencode"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit("Could not find opencode executable on PATH")


def parse_usage(text: str) -> dict[str, int | float | None]:
    usage: dict[str, int | float | None] = {
        "input_tokens": None,
        "base_input_tokens": None,
        "cache_creation_input_tokens": None,
        "cached_input_tokens": None,
        "billable_input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
    }
    totals = {
        "base_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    seen_tokens = False
    seen_cost = False

    def collect(holder: dict[str, object]) -> None:
        nonlocal seen_tokens, seen_cost
        tokens = holder.get("tokens")
        if not isinstance(tokens, dict):
            return
        seen_tokens = True
        base_input = tokens.get("input")
        output = tokens.get("output")
        total = tokens.get("total")
        cache = tokens.get("cache")
        cache_write = cache.get("write") if isinstance(cache, dict) else 0
        cache_read = cache.get("read") if isinstance(cache, dict) else 0
        if isinstance(base_input, int):
            totals["base_input_tokens"] += base_input
        if isinstance(cache_write, int):
            totals["cache_creation_input_tokens"] += cache_write
        if isinstance(cache_read, int):
            totals["cached_input_tokens"] += cache_read
        if isinstance(output, int):
            totals["output_tokens"] += output
        if isinstance(total, int):
            totals["total_tokens"] += total
        cost = holder.get("cost")
        if isinstance(cost, (int, float)):
            seen_cost = True
            totals["cost_usd"] += float(cost)

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part")
        if isinstance(part, dict) and isinstance(part.get("tokens"), dict):
            collect(part)
        elif isinstance(event.get("tokens"), dict):
            collect(event)
    if seen_tokens:
        usage["base_input_tokens"] = totals["base_input_tokens"]
        usage["cache_creation_input_tokens"] = totals["cache_creation_input_tokens"]
        usage["cached_input_tokens"] = totals["cached_input_tokens"]
        usage["billable_input_tokens"] = totals["base_input_tokens"] + totals["cache_creation_input_tokens"]
        usage["input_tokens"] = (
            totals["base_input_tokens"] + totals["cache_creation_input_tokens"] + totals["cached_input_tokens"]
        )
        usage["output_tokens"] = totals["output_tokens"]
        usage["total_tokens"] = totals["total_tokens"] or (
            int(usage["input_tokens"] or 0) + int(usage["output_tokens"] or 0)
        )
    if seen_cost:
        usage["cost_usd"] = totals["cost_usd"]
    return usage


def text_from_json_events(text: str) -> str:
    chunks: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    return "".join(chunks)


def extract_problem_context(row: dict, workspace: Path, window: int = 80) -> str:
    problem = row.get("problem_statement") or ""
    pattern = re.compile(
        r"github\.com/[^/]+/[^/]+/blob/[0-9A-Fa-f]{7,40}/(?P<path>[^)\s#]+)(?:#L(?P<line>\d+))?"
    )
    contexts: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(problem):
        rel_path = match.group("path").replace("/", os.sep)
        if rel_path in seen:
            continue
        seen.add(rel_path)
        file_path = workspace / rel_path
        if not file_path.is_file():
            continue
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        center = int(match.group("line") or "1")
        start = max(1, center - window)
        end = min(len(lines), center + window)
        body = "\n".join(f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1))
        contexts.append(f"File: {rel_path}\nLines {start}-{end}:\n{body}")
    return "\n\n".join(contexts)


def prompt_for_diff(row: dict, workspace: Path) -> str:
    fail_to_pass = json.loads(row.get("FAIL_TO_PASS") or "[]")
    problem = (row.get("problem_statement") or "").strip()
    if len(problem) > 3000:
        problem = problem[:3000] + "\n\n[Problem statement truncated for debug run.]"
    context = extract_problem_context(row, workspace)
    if not context:
        context = "No file excerpt was auto-extracted. Infer the minimal source file from the issue text."
    return f"""You are fixing one SWE-bench task.

Return ONLY a valid unified diff. Do not use tools. Do not explain. Do not use markdown fences.
The diff must start with "diff --git" and use repository-relative paths with a/ and b/ prefixes.
Make the smallest production-code change needed for the issue. Do not edit tests.

Instance: {row['instance_id']}
Repository: {row['repo']}
Base commit: {row['base_commit']}

Problem statement:
{problem}

Target tests expected to pass after the fix:
{json.dumps(fail_to_pass, ensure_ascii=False)}

Local file excerpts:
{context}
"""


def extract_unified_diff(text: str) -> str:
    fenced = re.search(r"```(?:diff|patch)?\s*\n(?P<body>.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group("body")
    else:
        marker = text.find("diff --git ")
        if marker < 0:
            return ""
        candidate = text[marker:]
    cleaned_lines = []
    for line in candidate.replace("\r\n", "\n").splitlines():
        if line.strip().startswith("```"):
            continue
        cleaned_lines.append(line.rstrip())
    return "\n".join(cleaned_lines).strip() + ("\n" if cleaned_lines else "")


def write_prediction(path: Path, instance_id: str, model_name: str, patch: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "instance_id": instance_id,
        "model_name_or_path": model_name,
        "model_patch": patch,
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_report(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def prompt_for_instance(
    row: dict,
    subagent_policy: str = "disabled",
) -> str:
    fail_to_pass = json.loads(row.get("FAIL_TO_PASS") or "[]")
    pass_to_pass = json.loads(row.get("PASS_TO_PASS") or "[]")
    problem = (row.get("problem_statement") or "").strip()
    if len(problem) > 4000:
        problem = problem[:4000] + "\n\n[Problem statement truncated for debug run.]"
    if subagent_policy == "forced":
        subagent_rule = (
            "- Before editing, launch exactly one task/subagent using category=\"deep\" or category=\"reviewer\" "
            "to inspect the local issue context and suggest the minimal fix. After it returns, make the final "
            "repository edits yourself. Do not launch more than one subagent."
        )
    elif subagent_policy == "optional-on-uncertainty":
        subagent_rule = (
            "- Solve the issue yourself first. You may launch at most one task/subagent using category=\"deep\" "
            "or category=\"reviewer\" only if local inspection leaves meaningful uncertainty, the fix touches "
            "multiple subsystems, an initial validation attempt fails, or the repair has high hidden-test risk. "
            "Ask the subagent for evidence: relevant files, risks, likely missing edge cases, and validation "
            "ideas, not for a final patch. Do not delegate routine single-file fixes."
        )
    elif subagent_policy == "post-patch-review":
        subagent_rule = (
            "- First inspect, edit, and validate the patch yourself. Do not launch a subagent before producing "
            "a candidate diff. After the candidate diff exists, launch exactly one task/subagent using "
            "category=\"reviewer\" or category=\"deep\" to review the diff for missed requirements, hidden-test "
            "risks, overfitting, and validation gaps. Ask for evidence-backed critique, not a replacement patch. "
            "Incorporate only concrete corrections that you can verify locally."
        )
    elif subagent_policy == "allowed":
        subagent_rule = "- You may launch task/subagent tools only when the active agent explicitly supports them."
    else:
        subagent_rule = "- Do not inspect git history, do not use web search, and do not launch task/subagent tools."
    return f"""You are fixing one SWE-bench task in this checked-out repository.

Rules:
- Modify repository files directly.
- Do not create unrelated files.
- Do not apply the provided gold patch; infer the fix from the issue.
- Keep the change minimal.
- The repository is already checked out at the pre-fix commit.
- Do not inspect git history and do not use web search.
{subagent_rule}
- Use only local source inspection and direct file edits needed for this issue.
- After editing, run only a small diff check, then stop.
- Do not print synthetic tool-call markup; use real tools only.
- When finished, briefly summarize the files changed.

Instance: {row['instance_id']}
Repository: {row['repo']}
Base commit: {row['base_commit']}

Problem statement:
{problem}

Target tests expected to pass after the fix:
{json.dumps(fail_to_pass, ensure_ascii=False)}

Regression tests expected to remain passing:
{json.dumps(pass_to_pass[:20], ensure_ascii=False)}
"""


def prepare_workspace(row: dict, workspace: Path, repo_cache: Path) -> None:
    workspace.parent.mkdir(parents=True, exist_ok=True)
    repo_cache.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists():
        def remove_readonly(func, path, _exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        shutil.rmtree(workspace, onerror=remove_readonly)
    if not repo_cache.exists():
        result = run(["git", "clone", "--mirror", repo_url(row["repo"]), str(repo_cache)], cwd=Path.cwd())
        if result.returncode != 0:
            raise SystemExit(redact(result.stderr or result.stdout))
    result = run(["git", "clone", str(repo_cache), str(workspace)], cwd=Path.cwd())
    if result.returncode != 0:
        raise SystemExit(redact(result.stderr or result.stdout))
    result = run(["git", "checkout", row["base_commit"]], cwd=workspace)
    if result.returncode != 0:
        raise SystemExit(redact(result.stderr or result.stdout))


def install_workspace_omo_config(workspace: Path, config_path: Path | None) -> None:
    if config_path is None:
        return
    target_dir = workspace / ".opencode"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "oh-my-openagent.jsonc").write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")


def run_opencode(
    *,
    row: dict,
    group: str,
    run_id: str,
    workspace: Path,
    output_dir: Path,
    env_file: Path,
    config: Path,
    provider: str,
    provider_name: str,
    model: str,
    agent: str,
    base_url_env: str,
    api_key_env: str,
    price_input_per_1m: float | None,
    price_cache_creation_input_per_1m: float | None,
    price_cached_input_per_1m: float | None,
    price_output_per_1m: float | None,
    generation_mode: str,
    subagent_policy: str,
    timeout: int,
) -> tuple[dict, str]:
    env_values = load_env(env_file)
    require_env_value(env_values, base_url_env, env_file)
    require_env_value(env_values, api_key_env, env_file)
    env = os.environ.copy()
    env.update(env_values)
    env["OPENCODE_CONFIG"] = str(config.resolve())

    output_dir.mkdir(parents=True, exist_ok=True)
    if generation_mode == "diff-output":
        prompt = prompt_for_diff(row, workspace)
        short_message = "Read the attached SWE-bench prompt and return only the requested unified diff."
    else:
        prompt = prompt_for_instance(
            row,
            subagent_policy=subagent_policy,
        )
        short_message = "Read the attached SWE-bench prompt and fix the repository."
    prompt_file = output_dir / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    command = [
        find_opencode(),
        "run",
        "--format",
        "json",
        "--model",
        f"{provider}/{model}",
        "--title",
        run_id,
    ]
    if group != "baseline" and agent:
        command.extend(["--agent", agent])
    command.extend(
        [
            "--auto",
            f"--file={prompt_file.resolve()}",
            "--log-level",
            "ERROR",
        ]
    )
    if group == "baseline":
        command.append("--pure")
    command.append(short_message)

    started = time.time()
    result = run(command, cwd=workspace, env=env, timeout=timeout)
    ended = time.time()

    stdout = redact(result.stdout or "")
    stderr = redact(result.stderr or "")
    (output_dir / "stdout.jsonl").write_text(stdout, encoding="utf-8")
    (output_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    model_text = text_from_json_events(stdout)
    (output_dir / "model_output.txt").write_text(redact(model_text), encoding="utf-8")
    (output_dir / "command.json").write_text(
        json.dumps(
            {
                "command": command[:-1] + ["<prompt redacted to command.json>"],
                "returncode": result.returncode,
                "started_at_epoch": started,
                "ended_at_epoch": ended,
                "latency_ms": round((ended - started) * 1000, 3),
                "subagent_policy": subagent_policy,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    git_apply_returncode = None
    model_patch_bytes = None
    if generation_mode == "diff-output":
        model_patch = extract_unified_diff(model_text)
        model_patch_bytes = len(model_patch.encode("utf-8"))
        model_patch_path = output_dir / "model.patch"
        model_patch_path.write_text(model_patch, encoding="utf-8")
        if model_patch.strip():
            check_result = run(["git", "apply", "--check", str(model_patch_path.resolve())], cwd=workspace)
            (output_dir / "git_apply_check.stdout.txt").write_text(redact(check_result.stdout or ""), encoding="utf-8")
            (output_dir / "git_apply_check.stderr.txt").write_text(redact(check_result.stderr or ""), encoding="utf-8")
            if check_result.returncode == 0:
                apply_result = run(["git", "apply", "--whitespace=nowarn", str(model_patch_path.resolve())], cwd=workspace)
                git_apply_returncode = apply_result.returncode
                (output_dir / "git_apply.stdout.txt").write_text(redact(apply_result.stdout or ""), encoding="utf-8")
                (output_dir / "git_apply.stderr.txt").write_text(redact(apply_result.stderr or ""), encoding="utf-8")
            else:
                git_apply_returncode = check_result.returncode

    diff_result = run(["git", "diff", "--binary"], cwd=workspace)
    patch = diff_result.stdout or ""
    (output_dir / "patch.diff").write_text(patch, encoding="utf-8")

    usage = parse_usage(stdout)
    cost_usd = usage["cost_usd"]
    if cost_usd is None or (cost_usd == 0 and price_input_per_1m is not None and price_output_per_1m is not None):
        cost_usd = calculate_cost_usd(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            input_price_per_1m=price_input_per_1m,
            output_price_per_1m=price_output_per_1m,
            base_input_tokens=usage["base_input_tokens"],
            cache_creation_input_tokens=usage["cache_creation_input_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            cache_creation_input_price_per_1m=price_cache_creation_input_per_1m,
            cached_input_price_per_1m=price_cached_input_per_1m,
        )
    return (
        {
            "returncode": result.returncode,
            "latency_ms": round((ended - started) * 1000, 3),
            "input_tokens": usage["input_tokens"],
            "base_input_tokens": usage["base_input_tokens"],
            "cache_creation_input_tokens": usage["cache_creation_input_tokens"],
            "cached_input_tokens": usage["cached_input_tokens"],
            "billable_input_tokens": usage["billable_input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "cost_usd": cost_usd,
            "provider": provider,
            "provider_name": provider_name,
            "model": model,
            "generation_mode": generation_mode,
            "subagent_policy": subagent_policy,
            "model_patch_bytes": model_patch_bytes,
            "git_apply_returncode": git_apply_returncode,
        },
        patch,
    )


def resolve_subagent_policy(*, policy: str | None, allow_subagents: bool, require_subagent_delegation: bool) -> str:
    if require_subagent_delegation and policy and policy != "forced":
        raise SystemExit("--require-subagent-delegation conflicts with --subagent-policy other than forced")
    if require_subagent_delegation:
        return "forced"
    if policy:
        return policy
    if allow_subagents:
        return "allowed"
    return "disabled"


def run_harness(
    *,
    dataset_jsonl: Path,
    prediction: Path,
    instance_id: str,
    run_id: str,
    report_dir: Path,
    timeout: int,
) -> tuple[int, str, str]:
    command = (
        "cd /mnt/e/Research/深度内核 && "
        "UV_PROJECT_ENVIRONMENT=.venv-wsl uv run python -m swebench.harness.run_evaluation "
        f"--dataset_name {dataset_jsonl.as_posix()} "
        "--split test "
        f"--predictions_path {prediction.as_posix()} "
        f"--instance_ids {instance_id} "
        "--max_workers 1 "
        f"--run_id {run_id} "
        f"--report_dir {report_dir.as_posix()}"
    )
    result = run(["wsl", "-d", "my-old-linux", "--", "bash", "-lc", command], cwd=Path.cwd(), timeout=timeout)
    return result.returncode, redact(result.stdout or ""), redact(result.stderr or "")


def is_transient_harness_error(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}"
    transient_markers = (
        "SSLEOFError",
        "UNEXPECTED_EOF_WHILE_READING",
        "MaxRetryError",
        "HTTPSConnectionPool",
        "raw.githubusercontent.com",
        "Connection reset by peer",
        "Temporary failure in name resolution",
        "Read timed out",
    )
    return any(marker in text for marker in transient_markers)


def run_harness_with_retries(
    *,
    dataset_jsonl: Path,
    prediction: Path,
    instance_id: str,
    run_id: str,
    report_dir: Path,
    timeout: int,
    retries: int,
    retry_sleep: int,
) -> tuple[int, str, str, int]:
    attempts: list[tuple[int, str, str]] = []
    for attempt in range(retries + 1):
        code, stdout, stderr = run_harness(
            dataset_jsonl=dataset_jsonl,
            prediction=prediction,
            instance_id=instance_id,
            run_id=run_id,
            report_dir=report_dir,
            timeout=timeout,
        )
        attempts.append((code, stdout, stderr))
        if code == 0 or not is_transient_harness_error(stdout, stderr) or attempt >= retries:
            break
        print(f"== harness transient failure; retrying {attempt + 1}/{retries} after {retry_sleep}s")
        time.sleep(retry_sleep)

    final_code, final_stdout, final_stderr = attempts[-1]
    if len(attempts) == 1:
        return final_code, final_stdout, final_stderr, 0

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    for index, (code, stdout, stderr) in enumerate(attempts, 1):
        stdout_parts.append(f"===== harness attempt {index} returncode={code} =====\n{stdout}")
        stderr_parts.append(f"===== harness attempt {index} returncode={code} =====\n{stderr}")
    return final_code, "\n".join(stdout_parts), "\n".join(stderr_parts), len(attempts) - 1


def append_metrics(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def find_summary_report(model_name: str, run_id: str, report_dir: Path) -> Path:
    candidates: list[Path] = [
        Path(f"{model_name}.{run_id}.json"),
        report_dir / f"{model_name}.{run_id}.json",
    ]
    candidates.extend(sorted(Path.cwd().glob(f"*.{run_id}.json")))
    if report_dir.exists():
        candidates.extend(sorted(report_dir.rglob(f"*.{run_id}.json")))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(f"{model_name}.{run_id}.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one SWE-bench instance through baseline and/or OMO.")
    parser.add_argument("--instance-id", default="django__django-11790")
    parser.add_argument("--groups", nargs="+", choices=["baseline", "omo"], default=["baseline", "omo"])
    parser.add_argument("--dataset-jsonl", default="experiments/data/swe-bench-verified-mini/test.jsonl", type=Path)
    parser.add_argument("--env-file", default=".env.siliconflow", type=Path)
    parser.add_argument("--config", default="experiments/configs/debug-siliconflow/opencode.jsonc", type=Path)
    parser.add_argument("--stage", default="debug-siliconflow")
    parser.add_argument("--provider", default="siliconflow")
    parser.add_argument("--provider-name", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--model-env", default="SILICONFLOW_MODEL")
    parser.add_argument("--agent", default="", help="Optional OpenCode agent for non-baseline/OMO runs.")
    parser.add_argument("--omo-config", default=None, type=Path, help="Optional OMO config to install inside each workspace.")
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
    parser.add_argument("--base-url-env", default="SILICONFLOW_BASE_URL")
    parser.add_argument("--api-key-env", default="SILICONFLOW_API_KEY")
    parser.add_argument("--price-input-per-1m", type=float, default=None)
    parser.add_argument("--price-cache-creation-input-per-1m", type=float, default=None)
    parser.add_argument("--price-cached-input-per-1m", type=float, default=None)
    parser.add_argument("--price-output-per-1m", type=float, default=None)
    parser.add_argument("--workspace-root", default="experiments/workspaces/debug-siliconflow", type=Path)
    parser.add_argument("--cache-root", default="experiments/workspaces/cache", type=Path)
    parser.add_argument("--result-root", default="experiments/results", type=Path)
    parser.add_argument("--metrics", default="experiments/results/runs/metrics.jsonl", type=Path)
    parser.add_argument("--api-metrics", default="experiments/results/api_metrics/api_call_metrics.jsonl", type=Path)
    parser.add_argument(
        "--generation-mode",
        choices=["edit-workspace", "diff-output"],
        default="edit-workspace",
        help="edit-workspace lets OpenCode edit files directly; diff-output asks the model for a patch and applies it.",
    )
    parser.add_argument("--opencode-timeout", default=1800, type=int)
    parser.add_argument("--harness-timeout", default=2400, type=int)
    parser.add_argument("--harness-retries", default=2, type=int)
    parser.add_argument("--harness-retry-sleep", default=20, type=int)
    args = parser.parse_args()

    env_values = load_env(args.env_file)
    model = args.model or env_values.get(args.model_env, "")
    if not model:
        raise SystemExit(f"Model is empty. Pass --model or set {args.model_env} in {args.env_file}")
    provider_name = args.provider_name or args.provider
    subagent_policy = resolve_subagent_policy(
        policy=args.subagent_policy,
        allow_subagents=args.allow_subagents,
        require_subagent_delegation=args.require_subagent_delegation,
    )

    row = load_instance(args.dataset_jsonl, args.instance_id)
    summary: list[dict] = []
    for group in args.groups:
        run_id = f"{args.stage}-{args.generation_mode}-{group}-{args.instance_id}"
        workspace = args.workspace_root / args.generation_mode / group / args.instance_id
        repo_cache = args.cache_root / (row["repo"].replace("/", "__") + ".git")
        output_dir = args.result_root / "runs" / args.stage / run_id
        prediction_path = args.result_root / "predictions" / f"{run_id}.jsonl"
        report_dir = args.result_root / "reports"

        print(f"== {group}: preparing workspace {workspace}")
        prepare_workspace(row, workspace, repo_cache)
        if group != "baseline":
            install_workspace_omo_config(workspace, args.omo_config)
        print(f"== {group}: running OpenCode")
        opencode_metrics, patch = run_opencode(
            row=row,
            group=group,
            run_id=run_id,
            workspace=workspace,
            output_dir=output_dir,
            env_file=args.env_file,
            config=args.config,
            provider=args.provider,
            provider_name=provider_name,
            model=model,
            agent=args.agent,
            base_url_env=args.base_url_env,
            api_key_env=args.api_key_env,
            price_input_per_1m=args.price_input_per_1m,
            price_cache_creation_input_per_1m=(
                args.price_cache_creation_input_per_1m
                if args.price_cache_creation_input_per_1m is not None
                else args.price_input_per_1m
            ),
            price_cached_input_per_1m=(
                args.price_cached_input_per_1m
                if args.price_cached_input_per_1m is not None
                else args.price_input_per_1m
            ),
            price_output_per_1m=args.price_output_per_1m,
            generation_mode=args.generation_mode,
            subagent_policy=subagent_policy,
            timeout=args.opencode_timeout,
        )
        print(f"== {group}: patch bytes {len(patch.encode('utf-8'))}")
        model_name = f"{args.provider}-{args.generation_mode}-{group}-{model}"
        if patch.strip():
            write_prediction(prediction_path, args.instance_id, model_name, patch)
            print(f"== {group}: running SWE-bench harness")
            harness_code, harness_stdout, harness_stderr, harness_retry_count = run_harness_with_retries(
                dataset_jsonl=args.dataset_jsonl,
                prediction=prediction_path,
                instance_id=args.instance_id,
                run_id=run_id,
                report_dir=report_dir,
                timeout=args.harness_timeout,
                retries=args.harness_retries,
                retry_sleep=args.harness_retry_sleep,
            )
        else:
            harness_code, harness_stdout, harness_stderr = 99, "", "empty patch; harness skipped"
            harness_retry_count = 0

        (output_dir / "harness.stdout.txt").write_text(harness_stdout, encoding="utf-8")
        (output_dir / "harness.stderr.txt").write_text(harness_stderr, encoding="utf-8")
        summary_report = find_summary_report(model_name, run_id, report_dir)
        report = parse_report(summary_report)
        resolved = None
        if report:
            resolved = args.instance_id in set(report.get("resolved_ids", []))

        metrics_row = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_id": run_id,
            "stage": args.stage,
            "group": group,
            "instance_id": args.instance_id,
            "provider": args.provider,
            "provider_name": provider_name,
            "model": opencode_metrics["model"],
            "harness": "OpenCode" if group == "baseline" else "OpenCode + OMO plugin enabled",
            "generation_mode": args.generation_mode,
            "subagent_policy": subagent_policy,
            "price_input_per_1m": args.price_input_per_1m,
            "price_cache_creation_input_per_1m": (
                args.price_cache_creation_input_per_1m
                if args.price_cache_creation_input_per_1m is not None
                else args.price_input_per_1m
            ),
            "price_cached_input_per_1m": (
                args.price_cached_input_per_1m
                if args.price_cached_input_per_1m is not None
                else args.price_input_per_1m
            ),
            "price_output_per_1m": args.price_output_per_1m,
            "latency_ms": opencode_metrics["latency_ms"],
            "input_tokens": opencode_metrics["input_tokens"],
            "base_input_tokens": opencode_metrics["base_input_tokens"],
            "cache_creation_input_tokens": opencode_metrics["cache_creation_input_tokens"],
            "cached_input_tokens": opencode_metrics["cached_input_tokens"],
            "billable_input_tokens": opencode_metrics["billable_input_tokens"],
            "output_tokens": opencode_metrics["output_tokens"],
            "total_tokens": opencode_metrics["total_tokens"],
            "cost_usd": opencode_metrics["cost_usd"],
            "opencode_returncode": opencode_metrics["returncode"],
            "model_patch_bytes": opencode_metrics["model_patch_bytes"],
            "git_apply_returncode": opencode_metrics["git_apply_returncode"],
            "patch_path": str(output_dir / "patch.diff"),
            "patch_bytes": len(patch.encode("utf-8")),
            "prediction_path": str(prediction_path) if patch.strip() else "",
            "harness_returncode": harness_code,
            "harness_retry_count": harness_retry_count,
            "report_path": str(summary_report) if summary_report.exists() else "",
            "resolved": resolved,
        }
        append_metrics(args.metrics, metrics_row)
        append_metrics(args.api_metrics, metrics_row)
        summary.append(metrics_row)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
