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

Parametrized over scope rather than two near-identical test functions —
the only difference between the workspace and customer variants is which
engage_* function and kill-switch model is involved.
"""

import asyncio
import uuid

import pytest

from doda.application.kill_switch_service import engage_customer_kill_switch, engage_workspace_kill_switch
from doda.db import tenant_scoped_session
from doda.domain.security.kill_switch import CustomerKillSwitch, WorkspaceKillSwitch
from tests.integration.conftest import commit_and_return, two_racing_sessions


@pytest.mark.parametrize("scope", ["workspace", "customer"])
async def test_two_concurrent_engages_both_succeed_with_one_winner(db_available: bool, scope: str) -> None:
    customer_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    def engage(session, actor):
        if scope == "workspace":
            return engage_workspace_kill_switch(
                session, workspace_id=workspace_id, customer_id=customer_id, actor_id=actor, reason="incident"
            )
        return engage_customer_kill_switch(
            session, customer_id=customer_id, actor_id=actor, reason="incident"
        )

    cm1, session1, cm2, session2 = await two_racing_sessions(customer_id)

    switches = await asyncio.gather(
        commit_and_return(cm1, engage(session1, "user:admin1")),
        commit_and_return(cm2, engage(session2, "user:admin2")),
    )
    winners = [switch.engaged_by for switch in switches]

    # Both calls succeed (no IntegrityError reaches the caller); both agree
    # on who actually won the race, rather than each believing itself won.
    assert winners[0] == winners[1]
    assert winners[0] in ("user:admin1", "user:admin2")

    async with tenant_scoped_session(customer_id) as session:
        if scope == "workspace":
            switch = await session.get(WorkspaceKillSwitch, workspace_id)
        else:
            switch = await session.get(CustomerKillSwitch, customer_id)
        assert switch is not None
        assert switch.engaged_by == winners[0]
