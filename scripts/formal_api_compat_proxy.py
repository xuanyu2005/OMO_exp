from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request


STRIPPED_FIELDS = ("reasoning_effort", "verbosity")


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


def load_model_routes(path: Path | None, env_values: dict[str, str]) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Model route map must be a JSON object: {path}")

    routes: dict[str, dict[str, str]] = {}
    for model, route in data.items():
        if not isinstance(model, str) or not isinstance(route, dict):
            raise SystemExit(f"Invalid model route entry for {model!r} in {path}")

        base_url = route.get("base_url")
        api_key = route.get("api_key")
        base_url_env = str(route.get("base_url_env", "")).strip()
        api_key_env = str(route.get("api_key_env", "")).strip()
        upstream_model = route.get("upstream_model", model)

        if not isinstance(base_url, str) or not base_url:
            base_url = env_values.get(base_url_env, "") if base_url_env else ""
        if not isinstance(api_key, str) or not api_key:
            api_key = env_values.get(api_key_env, "") if api_key_env else ""
        if not base_url:
            raise SystemExit(f"Missing base URL for model route {model!r} in {path}")
        if not api_key:
            raise SystemExit(f"Missing API key for model route {model!r} in {path}")
        if not isinstance(upstream_model, str) or not upstream_model:
            raise SystemExit(f"Invalid upstream_model for model route {model!r} in {path}")

        routes[model] = {
            "base_url": base_url.rstrip("/"),
            "api_key": api_key,
            "upstream_model": upstream_model,
        }
    return routes


def prices_for_model(
    model: object,
    *,
    price_map: dict[str, dict[str, float]],
    input_price_per_1m: float,
    cache_creation_input_price_per_1m: float,
    cached_input_price_per_1m: float,
    output_price_per_1m: float,
) -> dict[str, float]:
    if isinstance(model, str) and model in price_map:
        return price_map[model]
    return {
        "input": input_price_per_1m,
        "cache_creation_input": cache_creation_input_price_per_1m,
        "cached_input": cached_input_price_per_1m,
        "output": output_price_per_1m,
    }


def redact_headers(headers: object) -> dict[str, str]:
    return {
        str(key): "<redacted>" if str(key).lower() == "authorization" else str(value)
        for key, value in dict(headers).items()
    }


def request_summary(body: dict[str, object], body_bytes: bytes, stripped: dict[str, object]) -> dict[str, object]:
    tools = body.get("tools")
    messages = body.get("messages")
    return {
        "model": body.get("model"),
        "max_tokens": body.get("max_tokens"),
        "stream": body.get("stream"),
        "stream_options": body.get("stream_options"),
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "body_bytes": len(body_bytes),
        "stripped": stripped,
    }


def parse_stream_usage(raw: bytes) -> dict[str, object] | None:
    text = raw.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line.removeprefix("data: ").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        usage = event.get("usage")
        if isinstance(usage, dict):
            return usage
    return None


def usage_cost(
    usage: dict[str, object] | None,
    *,
    model: object = None,
    input_price_per_1m: float,
    cache_creation_input_price_per_1m: float,
    cached_input_price_per_1m: float,
    output_price_per_1m: float,
) -> dict[str, object] | None:
    if not usage:
        return None

    prompt_tokens = usage.get("prompt_tokens")
    input_tokens = prompt_tokens if isinstance(prompt_tokens, int) else usage.get("input_tokens")
    completion_tokens = usage.get("completion_tokens")
    output_tokens = completion_tokens if isinstance(completion_tokens, int) else usage.get("output_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None

    prompt_details = usage.get("prompt_tokens_details")
    cached_tokens = 0
    if isinstance(prompt_details, dict) and isinstance(prompt_details.get("cached_tokens"), int):
        cached_tokens = prompt_details["cached_tokens"]
    elif isinstance(usage.get("cache_read_input_tokens"), int):
        cached_tokens = usage["cache_read_input_tokens"]

    cache_creation_input_tokens = usage.get("cache_creation_input_tokens")
    if not isinstance(cache_creation_input_tokens, int):
        cache_creation_input_tokens = 0

    if isinstance(prompt_tokens, int):
        billable_input_tokens = max(input_tokens - cached_tokens, 0)
        base_input_tokens = billable_input_tokens
        reported_input_tokens = input_tokens
    else:
        base_input_tokens = input_tokens
        billable_input_tokens = input_tokens + cache_creation_input_tokens
        reported_input_tokens = input_tokens + cache_creation_input_tokens + cached_tokens

    total_tokens = usage.get("total_tokens")
    if not isinstance(total_tokens, int):
        total_tokens = reported_input_tokens + output_tokens

    cost_usd = (
        base_input_tokens / 1_000_000 * input_price_per_1m
        + cache_creation_input_tokens / 1_000_000 * cache_creation_input_price_per_1m
        + cached_tokens / 1_000_000 * cached_input_price_per_1m
        + output_tokens / 1_000_000 * output_price_per_1m
    )
    return {
        "input_tokens": reported_input_tokens,
        "base_input_tokens": base_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cached_input_tokens": cached_tokens,
        "billable_input_tokens": billable_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "model": model,
        "price_input_per_1m": input_price_per_1m,
        "price_cache_creation_input_per_1m": cache_creation_input_price_per_1m,
        "price_cached_input_per_1m": cached_input_price_per_1m,
        "price_output_per_1m": output_price_per_1m,
        "cost_usd": round(cost_usd, 12),
    }


def make_handler(
    upstream_base_url: str,
    upstream_api_key: str,
    log_dir: Path,
    timeout: int,
    *,
    price_map: dict[str, dict[str, float]],
    model_routes: dict[str, dict[str, str]],
    input_price_per_1m: float,
    cache_creation_input_price_per_1m: float,
    cached_input_price_per_1m: float,
    output_price_per_1m: float,
):
    class CompatProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            with (log_dir / "server.log").open("a", encoding="utf-8") as fh:
                fh.write(fmt % args + "\n")

        def do_GET(self) -> None:
            self.forward()

        def do_POST(self) -> None:
            self.forward()

        def forward(self) -> None:
            started = time.time()
            log_dir.mkdir(parents=True, exist_ok=True)
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length else b""
            body = None
            stripped: dict[str, object] = {}
            outgoing_body = raw_body
            request_model = None

            content_type = self.headers.get("Content-Type", "")
            if raw_body and "application/json" in content_type:
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError:
                    body = None
                if isinstance(body, dict):
                    for field in STRIPPED_FIELDS:
                        if field in body:
                            stripped[field] = body.pop(field)
                    request_model = body.get("model")
                    if isinstance(request_model, str) and request_model in model_routes:
                        body["model"] = model_routes[request_model]["upstream_model"]
                    outgoing_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

            route = model_routes.get(request_model) if isinstance(request_model, str) else None
            routed_base_url = route["base_url"] if route else upstream_base_url.rstrip("/")
            routed_api_key = route["api_key"] if route else upstream_api_key
            upstream_url = routed_base_url + self.path
            req = request.Request(upstream_url, data=outgoing_body if self.command != "GET" else None, method=self.command)
            for key, value in self.headers.items():
                lower = key.lower()
                if lower in {"host", "content-length", "authorization", "connection", "accept-encoding"}:
                    continue
                req.add_header(key, value)
            req.add_header("Authorization", f"Bearer {routed_api_key}")
            if raw_body and "content-type" not in {key.lower() for key in req.headers}:
                req.add_header("Content-Type", "application/json")

            response_body = b""
            meta: dict[str, object]
            try:
                with request.urlopen(req, timeout=timeout) as response:
                    response_body = response.read()
                    meta = {
                        "status": response.status,
                        "reason": response.reason,
                        "headers": dict(response.headers),
                    }
            except error.HTTPError as exc:
                response_body = exc.read()
                meta = {
                    "status": exc.code,
                    "reason": exc.reason,
                    "headers": dict(exc.headers),
                }
            except Exception as exc:  # noqa: BLE001 - proxy should surface upstream errors.
                response_body = json.dumps(
                    {"error": {"type": "compat_proxy_error", "message": f"{type(exc).__name__}: {exc}"}},
                    ensure_ascii=False,
                ).encode("utf-8")
                meta = {"status": 599, "reason": type(exc).__name__, "headers": {"Content-Type": "application/json"}}

            status = int(meta["status"]) if isinstance(meta.get("status"), int) and int(meta["status"]) < 600 else 502
            self.send_response(status)
            headers = dict(meta.get("headers") or {})
            skipped_headers = {"content-encoding", "transfer-encoding", "connection", "content-length"}
            for key, value in headers.items():
                if key.lower() not in skipped_headers:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

            usage = parse_stream_usage(response_body)
            prices = prices_for_model(
                request_model,
                price_map=price_map,
                input_price_per_1m=input_price_per_1m,
                cache_creation_input_price_per_1m=cache_creation_input_price_per_1m,
                cached_input_price_per_1m=cached_input_price_per_1m,
                output_price_per_1m=output_price_per_1m,
            )
            response_record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "method": self.command,
                "path": self.path,
                "upstream_base_url": routed_base_url,
                "request_headers": redact_headers(self.headers),
                "request": request_summary(body, outgoing_body, stripped) if isinstance(body, dict) else None,
                "status": status,
                "upstream_status": meta.get("status"),
                "reason": meta.get("reason"),
                "latency_ms": round((time.time() - started) * 1000, 3),
                "response_bytes": len(response_body),
                "usage": usage,
                "cost": usage_cost(
                    usage,
                    model=request_model,
                    input_price_per_1m=prices["input"],
                    cache_creation_input_price_per_1m=prices["cache_creation_input"],
                    cached_input_price_per_1m=prices["cached_input"],
                    output_price_per_1m=prices["output"],
                ),
            }
            with (log_dir / "requests.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(response_record, ensure_ascii=False) + "\n")

    return CompatProxyHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Local compatibility proxy for formal OpenAI-compatible API runs.")
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--base-url-env", default="GPT_BASE_URL")
    parser.add_argument("--api-key-env", default="GPT_API_KEY")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18082, type=int)
    parser.add_argument("--log-dir", default="experiments/results/runs/formal-gpt/compat-proxy", type=Path)
    parser.add_argument("--upstream-timeout", default=1800, type=int)
    parser.add_argument("--price-input-per-1m", default=2.5, type=float)
    parser.add_argument("--price-cache-creation-input-per-1m", default=None, type=float)
    parser.add_argument("--price-cached-input-per-1m", default=0.25, type=float)
    parser.add_argument("--price-output-per-1m", default=15.0, type=float)
    parser.add_argument("--price-map", default=None, type=Path)
    parser.add_argument(
        "--model-routes",
        default=None,
        type=Path,
        help="Optional JSON map from requested model names to upstream base URL/API key env vars.",
    )
    args = parser.parse_args()

    env_values = os.environ.copy()
    env_values.update(load_env(args.env_file))
    upstream_base_url = env_values.get(args.base_url_env, "").rstrip("/")
    upstream_api_key = env_values.get(args.api_key_env, "")
    if not upstream_base_url:
        raise SystemExit(f"{args.base_url_env} is empty in {args.env_file}")
    if not upstream_api_key:
        raise SystemExit(f"{args.api_key_env} is empty in {args.env_file}")

    args.log_dir.mkdir(parents=True, exist_ok=True)
    handler = make_handler(
        upstream_base_url,
        upstream_api_key,
        args.log_dir,
        args.upstream_timeout,
        price_map=load_price_map(args.price_map),
        model_routes=load_model_routes(args.model_routes, env_values),
        input_price_per_1m=args.price_input_per_1m,
        cache_creation_input_price_per_1m=(
            args.price_cache_creation_input_per_1m
            if args.price_cache_creation_input_per_1m is not None
            else args.price_input_per_1m
        ),
        cached_input_price_per_1m=args.price_cached_input_per_1m,
        output_price_per_1m=args.price_output_per_1m,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"formal-api-compat-proxy listening on http://{args.host}:{args.port}", flush=True)
    print(f"upstream: {upstream_base_url}", flush=True)
    print(f"log_dir: {args.log_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
