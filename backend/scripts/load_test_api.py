"""NFR-PERF-001 verification ("P95 API read < 500 ms, Load test, Prometheus
histogram") — this requirement has never once been measured against this
codebase. Not wired into CI: shared CI runners have too much wall-clock
jitter to make a hard latency assertion reliable (it would either be
flaky or so loose it proves nothing), the same reasoning NFR-SEC-003's
"high CVE <=7 kun ichida" SLA is documented as process-owned rather than
CI-enforced. This script is the honest alternative — a real, repeatable
measurement against a real running backend + real Postgres, run and read
by a person, the same category of tool as verify_audit_chain_job.py.

Requires a running backend (`uvicorn doda.main:app`) and a session seeded
via seed_e2e_demo.py (or any real session/workspace).
"""

import argparse
import asyncio
import statistics
import time

import httpx

READ_ENDPOINTS = [
    "/v1/me/workspaces",
    "/v1/workspaces/{workspace_id}/tasks",
    "/v1/workspaces/{workspace_id}/actions",
    "/v1/workspaces/{workspace_id}/notifications",
    "/v1/workspaces/{workspace_id}/audit",
]


async def _timed_get(client: httpx.AsyncClient, path: str, headers: dict[str, str]) -> float:
    start = time.perf_counter()
    response = await client.get(path, headers=headers)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.raise_for_status()
    return elapsed_ms


async def _run_one_endpoint(
    client: httpx.AsyncClient, path: str, headers: dict[str, str], *, requests: int, concurrency: int
) -> list[float]:
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded() -> float:
        async with semaphore:
            return await _timed_get(client, path, headers)

    return await asyncio.gather(*(bounded() for _ in range(requests)))


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=100)[94]


async def main(base_url: str, session_id: str, workspace_id: str, requests: int, concurrency: int) -> bool:
    headers = {"Authorization": f"Bearer {session_id}"}
    all_passed = True

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        for template in READ_ENDPOINTS:
            path = template.format(workspace_id=workspace_id)
            samples = await _run_one_endpoint(
                client, path, headers, requests=requests, concurrency=concurrency
            )
            p95 = _p95(samples)
            passed = p95 < 500.0
            all_passed = all_passed and passed
            status = "PASS" if passed else "FAIL"
            print(
                f"{status}  {path:55s} p50={statistics.median(samples):7.1f}ms "
                f"p95={p95:7.1f}ms max={max(samples):7.1f}ms n={len(samples)}"
            )

    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session-id", required=True, help="A live session id (see seed_e2e_demo.py)")
    parser.add_argument("--workspace-id", required=True, help="A workspace the session's user belongs to")
    parser.add_argument("--requests", type=int, default=200, help="Requests per endpoint")
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    ok = asyncio.run(main(args.base_url, args.session_id, args.workspace_id, args.requests, args.concurrency))
    raise SystemExit(0 if ok else 1)
