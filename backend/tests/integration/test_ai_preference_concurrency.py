"""Proves set_user_ai_preference/set_workspace_ai_preference survive two
concurrent calls for the same (customer, user)/workspace — same shape as
test_notification_preference_concurrency.py: each caller may intend a
different value, so the fix applies each caller's own value to the row
rather than a raw IntegrityError or silently keeping whichever commits
first.
"""

import asyncio
import uuid

from doda.ai.types import Provider
from doda.application.ai_preference_service import set_user_ai_preference, set_workspace_ai_preference
from tests.integration.conftest import commit_and_return, two_racing_sessions


async def test_two_concurrent_user_preference_sets_both_succeed(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    user_id = uuid.uuid4()

    cm1, session1, cm2, session2 = await two_racing_sessions(customer_id)

    results = await asyncio.gather(
        commit_and_return(
            cm1,
            set_user_ai_preference(
                session1, customer_id=customer_id, user_id=user_id, provider=Provider.CLAUDE, model=None
            ),
        ),
        commit_and_return(
            cm2,
            set_user_ai_preference(
                session2, customer_id=customer_id, user_id=user_id, provider=Provider.GEMINI, model=None
            ),
        ),
    )
    reported = sorted(pref.provider.value for pref in results)
    assert reported == ["CLAUDE", "GEMINI"]  # each call reports its own intended value, no raw error


async def test_two_concurrent_workspace_preference_sets_both_succeed(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    cm1, session1, cm2, session2 = await two_racing_sessions(customer_id)

    results = await asyncio.gather(
        commit_and_return(
            cm1,
            set_workspace_ai_preference(
                session1,
                workspace_id=workspace_id,
                customer_id=customer_id,
                provider=Provider.OPENAI,
                model="gpt-5-mini",
            ),
        ),
        commit_and_return(
            cm2,
            set_workspace_ai_preference(
                session2,
                workspace_id=workspace_id,
                customer_id=customer_id,
                provider=Provider.CLAUDE,
                model="claude-sonnet-5",
            ),
        ),
    )
    reported = sorted(pref.provider.value for pref in results)
    assert reported == ["CLAUDE", "OPENAI"]
