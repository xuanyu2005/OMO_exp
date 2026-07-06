from __future__ import annotations
import argparse, json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--status-jsonl", type=Path, required=True)
parser.add_argument("--metrics", type=Path, required=True)
args = parser.parse_args()
statuses = [json.loads(x) for x in args.status_jsonl.read_text(encoding="utf-8").splitlines() if x.strip()] if args.status_jsonl.exists() else []
rows = [json.loads(x) for x in args.metrics.read_text(encoding="utf-8").splitlines() if x.strip()] if args.metrics.exists() else []
print("statuses started", sum(s.get("status") == "started" for s in statuses), "finished", sum(s.get("status") == "finished" for s in statuses), "failed", sum(s.get("status") == "failed" for s in statuses), "metrics_rows", len(rows))
print("resolved", sum(r.get("resolved") is True for r in rows), "unresolved", sum(r.get("resolved") is False for r in rows), "cost", round(sum(float(r.get("cost_usd") or 0) for r in rows), 6), "tokens", sum(int(r.get("total_tokens") or 0) for r in rows))
if rows:
    r = rows[-1]
    print("last_metric", r.get("instance_id"), "harness", r.get("harness_returncode"), "resolved", r.get("resolved"), "proxy_requests", r.get("proxy_request_count"), "cost", r.get("cost_usd"))
