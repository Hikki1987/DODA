"""Proves engage_workspace_kill_switch/engage_customer_kill_switch survive
two concurrent engages for the same scope without a raw IntegrityError —
exactly the moment multiple admins are most likely to both hit "engage" at
once (an active incident), so a confusing 500 here is worse than usual.

Found via the same forced-interleaving technique as
test_task_status_concurrency.py / test_approval_consume_concurrency.py:
two sessions both load switch=None before either commits, both attempt to
insert the same-primary-key row. The fix treats the loser's unique-
violation as success (both callers wanted "engaged", and it is) rather
than surfacing the database's constraint error — unlike
customer_service.invite_customer_member's duplicate-invite case, there is
no meaningful business error here.
"""

import asyncio
import uuid

from doda.application.kill_switch_service import engage_customer_kill_switch, engage_workspace_kill_switch
from doda.db import tenant_scoped_session
from doda.domain.security.kill_switch import CustomerKillSwitch, WorkspaceKillSwitch


async def test_two_concurrent_workspace_engages_both_succeed_with_one_winner(
    db_available: bool,
) -> None:
    customer_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    cm1 = tenant_scoped_session(customer_id)
    cm2 = tenant_scoped_session(customer_id)
    session1 = await cm1.__aenter__()
    session2 = await cm2.__aenter__()

    async def engage(cm, session, actor):
        switch = await engage_workspace_kill_switch(
            session, workspace_id=workspace_id, customer_id=customer_id, actor_id=actor, reason="incident"
        )
        await cm.__aexit__(None, None, None)
        return switch.engaged_by

    winners = await asyncio.gather(
        engage(cm1, session1, "user:admin1"),
        engage(cm2, session2, "user:admin2"),
    )

    # Both calls succeed (no IntegrityError reaches the caller); both agree
    # on who actually won the race, rather than each believing itself won.
    assert winners[0] == winners[1]
    assert winners[0] in ("user:admin1", "user:admin2")

    async with tenant_scoped_session(customer_id) as session:
        switch = await session.get(WorkspaceKillSwitch, workspace_id)
        assert switch is not None
        assert switch.engaged_by == winners[0]


async def test_two_concurrent_customer_engages_both_succeed_with_one_winner(
    db_available: bool,
) -> None:
    customer_id = uuid.uuid4()

    cm1 = tenant_scoped_session(customer_id)
    cm2 = tenant_scoped_session(customer_id)
    session1 = await cm1.__aenter__()
    session2 = await cm2.__aenter__()

    async def engage(cm, session, actor):
        switch = await engage_customer_kill_switch(
            session, customer_id=customer_id, actor_id=actor, reason="incident"
        )
        await cm.__aexit__(None, None, None)
        return switch.engaged_by

    winners = await asyncio.gather(
        engage(cm1, session1, "user:admin1"),
        engage(cm2, session2, "user:admin2"),
    )

    assert winners[0] == winners[1]
    assert winners[0] in ("user:admin1", "user:admin2")

    async with tenant_scoped_session(customer_id) as session:
        switch = await session.get(CustomerKillSwitch, customer_id)
        assert switch is not None
        assert switch.engaged_by == winners[0]
