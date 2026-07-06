from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_price_map(path: Path | None) -> dict[str, dict[str, float]]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Price map must be a JSON object: {path}")
    result: dict[str, dict[str, float]] = {}
    for model, prices in data.items():
        if not isinstance(model, str) or not isinstance(prices, dict):
            raise SystemExit(f"Invalid price map entry for {model!r} in {path}")
        result[model] = {
            "input": float(prices.get("input", 0.0)),
            "cache_creation_input": float(prices.get("cache_creation_input", prices.get("input", 0.0))),
            "cached_input": float(prices.get("cached_input", prices.get("input", 0.0))),
            "output": float(prices.get("output", 0.0)),
        }
    return result


def prices_for_row(
    row: dict[str, object],
    *,
    price_map: dict[str, dict[str, float]],
    input_price_per_1m: float,
    cache_creation_input_price_per_1m: float,
    cached_input_price_per_1m: float,
    output_price_per_1m: float,
) -> dict[str, float]:
    request = row.get("request")
    model = request.get("model") if isinstance(request, dict) else None
    if isinstance(model, str) and model in price_map:
        return price_map[model]
    return {
        "input": input_price_per_1m,
        "cache_creation_input": cache_creation_input_price_per_1m,
        "cached_input": cached_input_price_per_1m,
        "output": output_price_per_1m,
    }


def load_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not path.exists():
        raise SystemExit(f"Missing proxy request log: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def row_cost(
    row: dict[str, object],
    *,
    price_map: dict[str, dict[str, float]],
    input_price_per_1m: float,
    cache_creation_input_price_per_1m: float,
    cached_input_price_per_1m: float,
    output_price_per_1m: float,
) -> dict[str, object] | None:
    cost = row.get("cost")
    if isinstance(cost, dict) and isinstance(cost.get("cost_usd"), (int, float)):
        return cost

    usage = row.get("usage")
    if not isinstance(usage, dict):
        return None

    prompt_tokens = usage.get("prompt_tokens")
    input_tokens = prompt_tokens if isinstance(prompt_tokens, int) else usage.get("input_tokens")
    completion_tokens = usage.get("completion_tokens")
    output_tokens = completion_tokens if isinstance(completion_tokens, int) else usage.get("output_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    prices = prices_for_row(
        row,
        price_map=price_map,
        input_price_per_1m=input_price_per_1m,
        cache_creation_input_price_per_1m=cache_creation_input_price_per_1m,
        cached_input_price_per_1m=cached_input_price_per_1m,
        output_price_per_1m=output_price_per_1m,
    )
    prompt_details = usage.get("prompt_tokens_details")
    cached_input_tokens = 0
    if isinstance(prompt_details, dict) and isinstance(prompt_details.get("cached_tokens"), int):
        cached_input_tokens = prompt_details["cached_tokens"]
    elif isinstance(usage.get("cache_read_input_tokens"), int):
        cached_input_tokens = usage["cache_read_input_tokens"]

    cache_creation_input_tokens = usage.get("cache_creation_input_tokens")
    if not isinstance(cache_creation_input_tokens, int):
        cache_creation_input_tokens = 0

    if isinstance(prompt_tokens, int):
        billable_input_tokens = max(input_tokens - cached_input_tokens, 0)
        base_input_tokens = billable_input_tokens
        reported_input_tokens = input_tokens
    else:
        base_input_tokens = input_tokens
        billable_input_tokens = input_tokens + cache_creation_input_tokens
        reported_input_tokens = input_tokens + cache_creation_input_tokens + cached_input_tokens

    total_tokens = usage.get("total_tokens")
    if not isinstance(total_tokens, int):
        total_tokens = reported_input_tokens + output_tokens

    cost_usd = (
        base_input_tokens / 1_000_000 * prices["input"]
        + cache_creation_input_tokens / 1_000_000 * prices["cache_creation_input"]
        + cached_input_tokens / 1_000_000 * prices["cached_input"]
        + output_tokens / 1_000_000 * prices["output"]
    )
    request = row.get("request")
    model = request.get("model") if isinstance(request, dict) else None
    return {
        "input_tokens": reported_input_tokens,
        "base_input_tokens": base_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "billable_input_tokens": billable_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "model": model,
        "price_input_per_1m": prices["input"],
        "price_cache_creation_input_per_1m": prices["cache_creation_input"],
        "price_cached_input_per_1m": prices["cached_input"],
        "price_output_per_1m": prices["output"],
        "cost_usd": round(cost_usd, 12),
    }


def summarize(
    rows: list[dict[str, object]],
    *,
    price_map: dict[str, dict[str, float]],
    input_price_per_1m: float,
    cache_creation_input_price_per_1m: float,
    cached_input_price_per_1m: float,
    output_price_per_1m: float,
) -> dict[str, object]:
    successful_rows = [row for row in rows if row.get("status") == 200]
    usage_rows = [row for row in successful_rows if isinstance(row.get("usage"), dict)]
    costs = [
        cost
        for row in successful_rows
        if (
            cost := row_cost(
                row,
                price_map=price_map,
                input_price_per_1m=input_price_per_1m,
                cache_creation_input_price_per_1m=cache_creation_input_price_per_1m,
                cached_input_price_per_1m=cached_input_price_per_1m,
                output_price_per_1m=output_price_per_1m,
            )
        )
        is not None
    ]
    input_tokens = sum(int(cost.get("input_tokens") or 0) for cost in costs)
    output_tokens = sum(int(cost.get("output_tokens") or 0) for cost in costs)
    total_tokens = sum(int(cost.get("total_tokens") or 0) for cost in costs)
    base_input_tokens = sum(int(cost.get("base_input_tokens") or 0) for cost in costs)
    cache_creation_input_tokens = sum(int(cost.get("cache_creation_input_tokens") or 0) for cost in costs)
    cached_input_tokens = sum(int(cost.get("cached_input_tokens") or 0) for cost in costs)
    billable_input_tokens = sum(int(cost.get("billable_input_tokens") or 0) for cost in costs)
    cost_usd = sum(float(cost.get("cost_usd") or 0.0) for cost in costs)
    latency_ms = sum(float(row.get("latency_ms") or 0.0) for row in successful_rows)
    effective_prices = costs[0] if costs else {}
    model_costs: dict[str, dict[str, object]] = {}
    for cost in costs:
        model = str(cost.get("model") or "unknown")
        bucket = model_costs.setdefault(
            model,
            {
                "request_count": 0,
                "input_tokens": 0,
                "base_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cached_input_tokens": 0,
                "billable_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            },
        )
        bucket["request_count"] = int(bucket["request_count"]) + 1
        for key in (
            "input_tokens",
            "base_input_tokens",
            "cache_creation_input_tokens",
            "cached_input_tokens",
            "billable_input_tokens",
            "output_tokens",
            "total_tokens",
        ):
            bucket[key] = int(bucket[key]) + int(cost.get(key) or 0)
        bucket["cost_usd"] = round(float(bucket["cost_usd"]) + float(cost.get("cost_usd") or 0.0), 12)
    return {
        "request_count": len(rows),
        "successful_request_count": len(successful_rows),
        "input_tokens": input_tokens,
        "base_input_tokens": base_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "billable_input_tokens": billable_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "latency_ms_sum": round(latency_ms, 3),
        "price_input_per_1m": effective_prices.get("price_input_per_1m", input_price_per_1m),
        "price_cache_creation_input_per_1m": effective_prices.get(
            "price_cache_creation_input_per_1m",
            cache_creation_input_price_per_1m,
        ),
        "price_cached_input_per_1m": effective_prices.get("price_cached_input_per_1m", cached_input_price_per_1m),
        "price_output_per_1m": effective_prices.get("price_output_per_1m", output_price_per_1m),
        "cost_usd": round(cost_usd, 12),
        "model_costs": model_costs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize formal API compatibility proxy request metrics.")
    parser.add_argument("requests_jsonl", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--price-input-per-1m", default=2.5, type=float)
    parser.add_argument("--price-cache-creation-input-per-1m", default=None, type=float)
    parser.add_argument("--price-cached-input-per-1m", default=0.25, type=float)
    parser.add_argument("--price-output-per-1m", default=15.0, type=float)
    parser.add_argument("--price-map", default=None, type=Path)
    args = parser.parse_args()

    summary = summarize(
        load_rows(args.requests_jsonl),
        price_map=load_price_map(args.price_map),
        input_price_per_1m=args.price_input_per_1m,
        cache_creation_input_price_per_1m=(
            args.price_cache_creation_input_per_1m
            if args.price_cache_creation_input_per_1m is not None
            else args.price_input_per_1m
        ),
        cached_input_price_per_1m=args.price_cached_input_per_1m,
        output_price_per_1m=args.price_output_per_1m,
    )
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
