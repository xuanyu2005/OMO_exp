from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_row(row: dict) -> dict:
    return {
        "recorded_at": row.get("recorded_at"),
        "run_id": row.get("run_id"),
        "stage": row.get("stage", "debug-siliconflow"),
        "group": row.get("group"),
        "instance_id": row.get("instance_id"),
        "provider": row.get("provider", "siliconflow"),
        "provider_name": row.get("provider_name"),
        "model": row.get("model"),
        "harness": row.get("harness"),
        "generation_mode": row.get("generation_mode", ""),
        "subagent_policy": row.get("subagent_policy", ""),
        "price_input_per_1m": row.get("price_input_per_1m"),
        "price_cache_creation_input_per_1m": row.get("price_cache_creation_input_per_1m"),
        "price_cached_input_per_1m": row.get("price_cached_input_per_1m"),
        "price_output_per_1m": row.get("price_output_per_1m"),
        "latency_ms": row.get("latency_ms"),
        "input_tokens": row.get("input_tokens"),
        "base_input_tokens": row.get("base_input_tokens"),
        "cache_creation_input_tokens": row.get("cache_creation_input_tokens"),
        "cached_input_tokens": row.get("cached_input_tokens"),
        "billable_input_tokens": row.get("billable_input_tokens"),
        "output_tokens": row.get("output_tokens"),
        "total_tokens": row.get("total_tokens"),
        "cost_usd": row.get("cost_usd"),
        "proxy_request_count": row.get("proxy_request_count"),
        "proxy_successful_request_count": row.get("proxy_successful_request_count"),
        "proxy_latency_ms_sum": row.get("proxy_latency_ms_sum"),
        "opencode_returncode": row.get("opencode_returncode", row.get("returncode")),
        "model_patch_bytes": row.get("model_patch_bytes"),
        "git_apply_returncode": row.get("git_apply_returncode"),
        "patch_bytes": row.get("patch_bytes"),
        "harness_returncode": row.get("harness_returncode"),
        "harness_retry_count": row.get("harness_retry_count"),
        "resolved": row.get("resolved"),
        "patch_path": row.get("patch_path", ""),
        "prediction_path": row.get("prediction_path", ""),
        "report_path": row.get("report_path", ""),
        "notes": row.get("notes", ""),
    }


def has_real_api_metrics(row: dict) -> bool:
    return bool(row.get("run_id")) and (
        row.get("latency_ms") is not None
        or row.get("input_tokens") is not None
        or row.get("output_tokens") is not None
        or row.get("total_tokens") is not None
        or row.get("cost_usd") is not None
    )


def dedupe_latest(rows: list[dict]) -> list[dict]:
    by_run: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        normalized = normalize_row(row)
        canonical_run_id = run_id.removesuffix("-corrected")
        if canonical_run_id != run_id:
            normalized["run_id"] = canonical_run_id
            normalized["notes"] = (
                (normalized.get("notes") or "")
                + " Synced from corrected token/cost extraction; no extra API call."
            ).strip()
        # Prefer corrected rows or richer rows with token/cost fields populated.
        current = by_run.get(canonical_run_id)
        if current is None:
            by_run[canonical_run_id] = normalized
            order.append(canonical_run_id)
            continue
        current_score = sum(current.get(k) is not None for k in ("input_tokens", "output_tokens", "total_tokens", "cost_usd"))
        new_score = sum(normalized.get(k) is not None for k in ("input_tokens", "output_tokens", "total_tokens", "cost_usd"))
        if new_score >= current_score:
            by_run[canonical_run_id] = normalized
    return [by_run[run_id] for run_id in order]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a dedicated API-call metrics log from experiment metrics rows."
    )
    parser.add_argument("--source", default="experiments/results/runs/metrics.jsonl", type=Path)
    parser.add_argument("--output", default="experiments/results/api_metrics/api_call_metrics.jsonl", type=Path)
    parser.add_argument("--summary", default="experiments/results/api_metrics/api_call_metrics_summary.md", type=Path)
    args = parser.parse_args()

    source_rows = [row for row in read_jsonl(args.source) if has_real_api_metrics(row)]
    rows = dedupe_latest(source_rows)
    write_jsonl(args.output, rows)

    total_cost = sum(float(row.get("cost_usd") or 0) for row in rows)
    total_tokens = sum(int(row.get("total_tokens") or 0) for row in rows)
    lines = [
        "# API Call Metrics Summary",
        "",
        f"- Source: `{args.source}`",
        f"- JSONL log: `{args.output}`",
        f"- API call rows: {len(rows)}",
        f"- Total tokens: {total_tokens}",
        f"- Total cost: {total_cost:.8f}",
        "",
        "| Run ID | Group | Instance | Mode | Subagent policy | Harness | Latency ms | Tokens | Cost | Return | Model patch bytes | Git apply | Patch bytes | Harness return | Resolved |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {run_id} | {group} | {instance_id} | {generation_mode} | {subagent_policy} | {harness} | {latency_ms} | {total_tokens} | {cost_usd} | {opencode_returncode} | {model_patch_bytes} | {git_apply_returncode} | {patch_bytes} | {harness_returncode} | {resolved} |".format(
                run_id=row.get("run_id"),
                group=row.get("group"),
                instance_id=row.get("instance_id"),
                generation_mode=row.get("generation_mode"),
                subagent_policy=row.get("subagent_policy"),
                harness=row.get("harness"),
                latency_ms=row.get("latency_ms"),
                total_tokens=row.get("total_tokens"),
                cost_usd=row.get("cost_usd"),
                opencode_returncode=row.get("opencode_returncode"),
                model_patch_bytes=row.get("model_patch_bytes"),
                git_apply_returncode=row.get("git_apply_returncode"),
                patch_bytes=row.get("patch_bytes"),
                harness_returncode=row.get("harness_returncode"),
                resolved=row.get("resolved"),
            )
        )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} API metrics row(s) to {args.output}")
    print(f"Wrote summary to {args.summary}")
    print(f"total_tokens={total_tokens}")
    print(f"total_cost={total_cost:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
