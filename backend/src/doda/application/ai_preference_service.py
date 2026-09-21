"""Provider/model selection — the resolution chain the multi-provider
instruction specifies, in priority order:

  1. the conversation's own pin (`Conversation.pinned_provider/model`,
     set only by an explicit in-conversation switch — see
     `doda.application.conversation_service.switch_conversation_provider`)
  2. the caller's personal default (`UserAIPreference`)
  3. the workspace's default (`WorkspaceAIPreference`)
  4. the system default (`doda.config.Settings.ai_default_provider` +
     `ai_model_*`)

Each tier resolves BOTH provider and model together — there is no
"provider from tier 2, model from tier 3" mixing, so switching tiers
never silently pairs a provider-level preference with an unrelated
model choice. Setting one tier's preference deliberately never rewrites
another tier's stored row (the explicit instruction: changing the
default must not retroactively change existing conversations' choice,
and pinning a conversation must not change the user's or workspace's
saved default).
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from doda.ai.types import Provider
from doda.application.audit_service import record_audit_event
from doda.config import Settings
from doda.domain.ai_preference.models import PreferenceProvider, UserAIPreference, WorkspaceAIPreference
from doda.domain.conversation.models import Conversation


class ResolvedProviderChoice:
    __slots__ = ("provider", "model")

    def __init__(self, provider: Provider, model: str | None) -> None:
        self.provider = provider
        self.model = model


def default_model_for(settings: Settings, provider: Provider) -> str:
    return {
        Provider.OPENAI: settings.ai_model_openai,
        Provider.GEMINI: settings.ai_model_gemini,
        Provider.CLAUDE: settings.ai_model_claude,
    }[provider]


async def resolve_provider_choice(
    session: AsyncSession,
    *,
    settings: Settings,
    conversation: Conversation,
    customer_id: uuid.UUID,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> ResolvedProviderChoice:
    if conversation.pinned_provider is not None:
        provider = Provider(conversation.pinned_provider)
        return ResolvedProviderChoice(
            provider, conversation.pinned_model or default_model_for(settings, provider)
        )

    user_pref = await session.get(UserAIPreference, (customer_id, user_id))
    if user_pref is not None:
        provider = Provider(user_pref.provider.value)
        return ResolvedProviderChoice(provider, user_pref.model or default_model_for(settings, provider))

    workspace_pref = await session.get(WorkspaceAIPreference, workspace_id)
    if workspace_pref is not None:
        provider = Provider(workspace_pref.provider.value)
        return ResolvedProviderChoice(provider, workspace_pref.model or default_model_for(settings, provider))

    provider = Provider(settings.ai_default_provider)
    return ResolvedProviderChoice(provider, default_model_for(settings, provider))


async def get_user_ai_preference(
    session: AsyncSession, *, customer_id: uuid.UUID, user_id: uuid.UUID
) -> UserAIPreference | None:
    return await session.get(UserAIPreference, (customer_id, user_id))


async def get_workspace_ai_preference(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> WorkspaceAIPreference | None:
    return await session.get(WorkspaceAIPreference, workspace_id)


async def set_user_ai_preference(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: Provider,
    model: str | None,
) -> UserAIPreference:
    """Race-safe "set X" upsert — same shape as `notification_service.
    set_notification_preference`: two concurrent saves (a double-click,
    or the same person on two devices) both seeing no existing row both
    try to insert; the loser's IntegrityError is caught and its own
    (last-write-wins) value applied to the row the winner just
    committed, rather than a raw 500 or silently keeping the winner's
    value."""
    pref = await session.get(UserAIPreference, (customer_id, user_id))
    if pref is not None:
        pref.provider = PreferenceProvider(provider.value)
        pref.model = model
        await session.flush()
    else:
        pref = UserAIPreference(
            customer_id=customer_id, user_id=user_id, provider=PreferenceProvider(provider.value), model=model
        )
        try:
            async with session.begin_nested():
                session.add(pref)
                await session.flush()
        except IntegrityError:
            pref = await session.get(UserAIPreference, (customer_id, user_id))
            assert pref is not None
            pref.provider = PreferenceProvider(provider.value)
            pref.model = model
            await session.flush()

    await record_audit_event(
        session,
        customer_id=customer_id,
        trace_id=uuid.uuid4(),
        actor_id=f"user:{user_id}",
        event_type="ai_preference.user_set.v1",
        safe_metadata={"provider": provider.value, "model": model},
    )
    return pref


async def set_workspace_ai_preference(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    customer_id: uuid.UUID,
    actor_id: str,
    provider: Provider,
    model: str | None,
) -> WorkspaceAIPreference:
    """Same race-safe upsert shape as `set_user_ai_preference` above.
    FR-ADM-006: "O'zgarish darhol qo'llanadi va audit qilinadi" — the
    "applies immediately" half was always true (the next chat turn just
    reads the row), but nothing ever recorded the change itself until
    this audit call was added."""
    pref = await session.get(WorkspaceAIPreference, workspace_id)
    if pref is not None:
        pref.provider = PreferenceProvider(provider.value)
        pref.model = model
        await session.flush()
    else:
        pref = WorkspaceAIPreference(
            workspace_id=workspace_id,
            customer_id=customer_id,
            provider=PreferenceProvider(provider.value),
            model=model,
        )
        try:
            async with session.begin_nested():
                session.add(pref)
                await session.flush()
        except IntegrityError:
            pref = await session.get(WorkspaceAIPreference, workspace_id)
            assert pref is not None
            pref.provider = PreferenceProvider(provider.value)
            pref.model = model
            await session.flush()

    await record_audit_event(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="ai_preference.workspace_set.v1",
        safe_metadata={"provider": provider.value, "model": model},
    )
    return pref


async def clear_user_ai_preference(
    session: AsyncSession, *, customer_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """ "OpenAI standartiga qaytish" (revert to the system default) — the
    instruction's own phrasing implies reverting, not merely re-setting
    to OPENAI explicitly (which would itself be indistinguishable from a
    deliberate OpenAI preference later if the system default ever
    changes) — deleting the row is the honest representation of "no
    personal override". Reverting is itself a change, so it is audited
    the same as setting one (FR-ADM-006) — but only when there was
    actually a row to clear; a no-op clear (nothing was set) is not a
    change and would otherwise pollute the trail with events that
    describe nothing happening."""
    pref = await session.get(UserAIPreference, (customer_id, user_id))
    if pref is not None:
        await session.delete(pref)
        await session.flush()
        await record_audit_event(
            session,
            customer_id=customer_id,
            trace_id=uuid.uuid4(),
            actor_id=f"user:{user_id}",
            event_type="ai_preference.user_cleared.v1",
        )


async def clear_workspace_ai_preference(
    session: AsyncSession, *, workspace_id: uuid.UUID, customer_id: uuid.UUID, actor_id: str
) -> None:
    """Same revert-to-default semantics as `clear_user_ai_preference`,
    one tier up."""
    pref = await session.get(WorkspaceAIPreference, workspace_id)
    if pref is not None:
        await session.delete(pref)
        await session.flush()
        await record_audit_event(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            trace_id=uuid.uuid4(),
            actor_id=actor_id,
            event_type="ai_preference.workspace_cleared.v1",
        )
