"""Proves `resolve_provider_choice`'s actual PRIORITY CHAIN — not just
that each tier's set/get/clear endpoint round-trips (already tested in
test_ai_settings_api.py), but that a stored preference actually changes
which provider a real resolution picks, and that a higher tier really
does win over a lower one. The conversation-pin (tier 1) and system-
default (tier 4) branches are already exercised via test_conversations_
api.py's real chat-turn tests; tiers 2 (user) and 3 (workspace) were
never exercised at all before this file — `resolve_provider_choice`
could have silently ignored either table and no test would have failed.
"""

import uuid

from doda.ai.types import Provider
from doda.application.ai_preference_service import (
    resolve_provider_choice,
    set_user_ai_preference,
    set_workspace_ai_preference,
)
from doda.config import get_settings
from doda.db import tenant_scoped_session
from doda.domain.conversation.models import Conversation
from tests.integration.conftest import seed_workspace_member


def _unpinned_conversation(customer_id: uuid.UUID, workspace_id: uuid.UUID) -> Conversation:
    return Conversation(customer_id=customer_id, workspace_id=workspace_id, owner_id="user:test")


async def test_a_users_own_preference_is_actually_used_when_no_conversation_pin_exists(
    db_available: bool,
) -> None:
    member = await seed_workspace_member()
    settings = get_settings()

    async with tenant_scoped_session(member.customer_id) as db:
        await set_user_ai_preference(
            db, customer_id=member.customer_id, user_id=member.user_id, provider=Provider.CLAUDE, model=None
        )
        await db.commit()

    async with tenant_scoped_session(member.customer_id) as db:
        conversation = _unpinned_conversation(member.customer_id, member.workspace_id)
        choice = await resolve_provider_choice(
            db,
            settings=settings,
            conversation=conversation,
            customer_id=member.customer_id,
            user_id=member.user_id,
            workspace_id=member.workspace_id,
        )
    assert choice.provider is Provider.CLAUDE


async def test_a_workspaces_default_is_used_when_no_user_preference_is_set(db_available: bool) -> None:
    member = await seed_workspace_member()
    settings = get_settings()

    async with tenant_scoped_session(member.customer_id) as db:
        await set_workspace_ai_preference(
            db,
            workspace_id=member.workspace_id,
            customer_id=member.customer_id,
            actor_id="user:test-admin",
            provider=Provider.GEMINI,
            model=None,
        )
        await db.commit()

    async with tenant_scoped_session(member.customer_id) as db:
        conversation = _unpinned_conversation(member.customer_id, member.workspace_id)
        choice = await resolve_provider_choice(
            db,
            settings=settings,
            conversation=conversation,
            customer_id=member.customer_id,
            user_id=member.user_id,
            workspace_id=member.workspace_id,
        )
    assert choice.provider is Provider.GEMINI


async def test_a_users_own_preference_wins_over_the_workspaces_default(db_available: bool) -> None:
    member = await seed_workspace_member()
    settings = get_settings()

    async with tenant_scoped_session(member.customer_id) as db:
        await set_workspace_ai_preference(
            db,
            workspace_id=member.workspace_id,
            customer_id=member.customer_id,
            actor_id="user:test-admin",
            provider=Provider.GEMINI,
            model=None,
        )
        await set_user_ai_preference(
            db, customer_id=member.customer_id, user_id=member.user_id, provider=Provider.CLAUDE, model=None
        )
        await db.commit()

    async with tenant_scoped_session(member.customer_id) as db:
        conversation = _unpinned_conversation(member.customer_id, member.workspace_id)
        choice = await resolve_provider_choice(
            db,
            settings=settings,
            conversation=conversation,
            customer_id=member.customer_id,
            user_id=member.user_id,
            workspace_id=member.workspace_id,
        )
    # Tier 2 (user) beats tier 3 (workspace) — the workspace default set
    # above must never leak through just because it was set first.
    assert choice.provider is Provider.CLAUDE
