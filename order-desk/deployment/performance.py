"""Explicit small-fixture HTTPS latency gate; not a production capacity claim."""

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from probe import request

fixture = json.loads(Path("/run-state/fixture.json").read_text(encoding="utf-8"))
workflow = json.loads(Path("/run-state/workflow.json").read_text(encoding="utf-8"))
cookies = json.loads(Path("/run-state/session.json").read_text(encoding="utf-8"))
headers = {"Cookie": "; ".join(f"{c['name']}={c['value']}" for c in cookies)}
workspace = fixture["a"]
capacity = Path("/run-state/performance-fixture.json")
workload = (
    json.loads(capacity.read_text(encoding="ascii")) if capacity.exists() else None
)
if workload:
    workspace = workload["workspace"]
    workflow.update(draft=workload["draft"], source=workload["source"])
routes = {
    "catalogue": f"/api/v1/workspaces/{workspace}/catalog/items/",
    "drafts": f"/api/v1/workspaces/{workspace}/draft-orders/",
    "order_queue": f"/api/v1/workspaces/{workspace}/orders/queue/",
    "readiness": (
        f"/api/v1/workspaces/{workspace}/draft-orders/{workflow['draft']}/readiness/"
    ),
    "source_order": f"/api/v1/workspaces/{workspace}/orders/{workflow['source']}/",
    "private_export": workflow["artifact"]["download_url"],
}
targets = {"read_p95_ms": 500, "error_rate": 0, "throughput_rps": 10}


def measure(pair):
    name, path = pair
    start = time.perf_counter()
    status, _, content = request(path, headers=headers)
    return name, (time.perf_counter() - start) * 1000, status, len(content)


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


# Warm every endpoint, then 8 simultaneous clients with a new validated TLS
# connection per request. A closed-loop burst measures latency, not saturation.
for pair in routes.items():
    if measure(pair)[2] != 200:
        raise RuntimeError("Performance fixture/authorization is not ready.")
samples = list(routes.items()) * 40
start = time.perf_counter()
with ThreadPoolExecutor(max_workers=8) as executor:
    results = list(executor.map(measure, samples))
seconds = time.perf_counter() - start
latencies = [r[1] for r in results]
errors = sum(r[2] != 200 for r in results)
report = {
    "profile": "synthetic-local-https-v2-with-order-queue",
    "fixture_counts": workload["counts"] if workload else "browser acceptance fixture",
    "targets_provisional": targets,
    "clients": 8,
    "requests": len(results),
    "seconds": round(seconds, 3),
    "rps": round(len(results) / seconds, 3),
    "errors": errors,
    "p50_ms": round(percentile(latencies, 0.5), 3),
    "p95_ms": round(percentile(latencies, 0.95), 3),
    "p99_ms": round(percentile(latencies, 0.99), 3),
    "max_bytes": max(r[3] for r in results),
    "routes": {
        name: {
            "requests": sum(r[0] == name for r in results),
            "p95_ms": round(
                percentile([r[1] for r in results if r[0] == name], 0.95), 3
            ),
        }
        for name in routes
    },
}
report["result"] = (
    "PASS"
    if report["p95_ms"] <= targets["read_p95_ms"]
    and all(
        route["p95_ms"] <= targets["read_p95_ms"] for route in report["routes"].values()
    )
    and errors == targets["error_rate"]
    and report["rps"] >= targets["throughput_rps"]
    else "FAILED"
)
print(json.dumps(report, sort_keys=True))
if report["result"] != "PASS":
    raise RuntimeError("Provisional small-fixture performance target failed.")
