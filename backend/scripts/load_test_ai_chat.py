"""NFR-PERF-002/003 verification — "AI First meaningful output <8s (P95),
trace-based o'lchov" and "50 parallel chat sessions degradatsiyasiz" —
neither has ever been measured against this codebase. Same category of
tool as load_test_api.py (NFR-PERF-001): not wired into CI (shared
runners' wall-clock jitter makes a hard latency assertion either flaky
or meaningless — same reasoning NFR-SEC-003's SLA is process-owned, not
CI-enforced), a real, repeatable measurement against a real running
backend + real Postgres, run and read by a person.

Requires a running backend (`uvicorn doda.main:app`). Unlike
load_test_api.py, this script does NOT take a pre-seeded session —
"50 parallel chat sessions" in a multi-tenant SaaS realistically means
50 DIFFERENT customers chatting at once (each with its own
AIBudgetLedger row, i.e. its own `SELECT ... FOR UPDATE` lock — see
`ai_budget_service.py`), not 50 concurrent turns fighting over one
customer's budget lock, which would measure lock contention, not chat
throughput. So this script seeds N fresh customer/workspace/user/session
tuples directly via the DB (the same dev/test seam
`scripts/seed_e2e_demo.py` uses), one conversation each, then fires all N
first-turn chat messages concurrently.

**Honest limit, stated up front, not discovered mid-run**: no real AI
provider credential exists in this environment (ADR-008/ADR-009's network
policy), so every turn actually runs `doda.ai.port.NullModelGateway` —
a single in-process text-formatting call with no network round trip.
The absolute latency numbers below therefore do NOT measure a real
provider's response time; they measure DODA's OWN overhead per turn
(session/authz resolution, message persistence, budget reserve/
reconcile, SSE framing) — the part actually within this codebase's
control, and the part that would additively stack on top of whatever a
real provider adds. Run this again once a real provider key is
configured for a true end-to-end reading.
"""

import argparse
import asyncio
import statistics
import time
import uuid

import httpx

from doda.application.session_service import create_session
from doda.application.workspace_service import create_workspace
from doda.db import tenant_scoped_session
from doda.domain.customer.models import Customer, CustomerMembership
from doda.domain.identity.models import AuthStrength, User
from doda.domain.workspace.models import WorkspaceMembership


async def _seed_one_customer_session() -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (session_id, workspace_id) for one fresh, independent
    customer — mirrors conftest.py's seed_workspace_member, as a
    standalone script instead of a pytest fixture (same reason
    seed_e2e_demo.py bypasses the public API: no real OIDC round trip
    to drive headlessly here)."""
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        user = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Load Test User")
        db.add(user)
        await db.flush()

        db.add(Customer(id=customer_id, name="Load Test Customer"))
        await db.flush()

        membership = CustomerMembership(customer_id=customer_id, user_id=user.id, role="member")
        db.add(membership)
        await db.flush()

        workspace = await create_workspace(db, customer_id=customer_id, name="Load Test Workspace")
        db.add(
            WorkspaceMembership(
                customer_id=customer_id,
                customer_membership_id=membership.id,
                workspace_id=workspace.id,
                role="workspace_admin",
            )
        )
        await db.flush()

        session_record = await create_session(db, user_id=user.id, auth_strength=AuthStrength.AAL1)
        return session_record.id, workspace.id


async def _one_chat_turn(
    client: httpx.AsyncClient, *, session_id: uuid.UUID, workspace_id: uuid.UUID
) -> float:
    """Creates a conversation and posts one message, returning time-to-
    first-byte in milliseconds (the SSE stream's first chunk) — the
    closest available proxy for NFR-PERF-002's "first meaningful
    output"."""
    headers = {"Authorization": f"Bearer {session_id}"}
    created = await client.post(f"/v1/workspaces/{workspace_id}/conversations", json={}, headers=headers)
    created.raise_for_status()
    conversation_id = created.json()["id"]

    start = time.perf_counter()
    first_byte_ms: float | None = None
    async with client.stream(
        "POST",
        f"/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
        json={"content": "Salom, bugungi ish rejasini tuzib bering", "mode": "STANDARD"},
        headers=headers,
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            if chunk and first_byte_ms is None:
                first_byte_ms = (time.perf_counter() - start) * 1000

    assert first_byte_ms is not None, "stream produced no bytes at all"
    return first_byte_ms


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=100)[94] if len(samples) > 1 else samples[0]


async def main(base_url: str, sessions: int) -> bool:
    print(f"Seeding {sessions} independent customer/workspace/session tuples...")
    seeded = await asyncio.gather(*(_seed_one_customer_session() for _ in range(sessions)))

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        print("Baseline: one isolated chat turn (no concurrency)...")
        baseline_session_id, baseline_workspace_id = seeded[0]
        baseline_ms = await _one_chat_turn(
            client, session_id=baseline_session_id, workspace_id=baseline_workspace_id
        )
        print(f"  baseline first-byte latency: {baseline_ms:7.1f}ms")

        print(f"Running {sessions} concurrent chat turns (one per customer)...")
        samples = await asyncio.gather(
            *(
                _one_chat_turn(client, session_id=session_id, workspace_id=workspace_id)
                for session_id, workspace_id in seeded
            )
        )

    p50 = statistics.median(samples)
    p95 = _p95(samples)
    worst = max(samples)
    latency_ok = p95 < 8000.0
    # "degradatsiyasiz" (without degradation): concurrent P95 should not
    # blow up relative to the single-session baseline. 3x is a generous
    # margin — this environment's NullModelGateway turn is dominated by
    # DB round trips, which do slow down somewhat under concurrency by
    # nature of shared connection-pool/CPU, not a hard SLA number from
    # the TRD itself (which only says "without degradation").
    degradation_ok = p95 < baseline_ms * 3
    all_passed = latency_ok and degradation_ok

    print(
        f"{'PASS' if latency_ok else 'FAIL'}  NFR-PERF-002 (<8s P95 first output)  "
        f"p50={p50:7.1f}ms p95={p95:7.1f}ms max={worst:7.1f}ms n={len(samples)}"
    )
    print(
        f"{'PASS' if degradation_ok else 'FAIL'}  NFR-PERF-003 (no degradation @ {sessions} concurrent)  "
        f"baseline={baseline_ms:7.1f}ms concurrent_p95={p95:7.1f}ms (ratio={p95 / baseline_ms:.2f}x)"
    )
    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--sessions", type=int, default=50, help="Concurrent chat sessions (NFR-PERF-003: 50)"
    )
    args = parser.parse_args()

    ok = asyncio.run(main(args.base_url, args.sessions))
    raise SystemExit(0 if ok else 1)
