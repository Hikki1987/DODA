"""AI provider settings endpoints — the multi-provider instruction's
"settings UI distinguishing key-configured from API-verified-working,
with per-provider test-connection/enable-disable/set-default controls."
Same authoritative-chain pattern as every other endpoint in this
codebase: tenant/authz context only from RequestContext/
CustomerRequestContext, never a client-supplied customer_id/workspace_id
that bypasses it.

Three customer-scoped routes (`authorize_manage_ai_provider_settings`:
CustomerOwner-only, same restrictiveness as kill switch/audit/archived
workspaces — this affects every workspace under the customer, not just
the caller's own) plus two preference pairs (self-service "my default",
any chat-authorized member; workspace default,
`authorize_manage_workspace_ai_preference`: WorkspaceAdmin/CustomerOwner).
"""

from fastapi import APIRouter, Depends

from doda.ai.factory import is_provider_configured
from doda.ai.types import Provider
from doda.api.ai_settings_schemas import (
    AIFallbackSettingOut,
    AIPreferenceOut,
    ProviderStatusOut,
    SetAIFallbackSettingRequest,
    SetAIPreferenceRequest,
    SetProviderEnabledRequest,
    TestProviderConnectionOut,
)
from doda.api.dependencies import (
    CustomerRequestContext,
    RequestContext,
    get_customer_request_context,
    get_request_context,
)
from doda.application import ai_preference_service, ai_provider_settings_service
from doda.application.authz_service import (
    authorize_manage_ai_provider_settings,
    authorize_manage_workspace_ai_preference,
    authorize_use_chat,
)
from doda.config import get_settings

router = APIRouter(tags=["ai-settings"])


@router.get("/v1/customers/{customer_id}/ai-providers", response_model=list[ProviderStatusOut])
async def list_provider_statuses(
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> list[ProviderStatusOut]:
    """Any customer member can see this — whether a chat can use a given
    provider is not sensitive the way a credential itself would be."""
    settings = get_settings()
    out = []
    for provider in Provider:
        enabled = await ai_provider_settings_service.is_provider_enabled_for_customer(
            ctx.db, customer_id=ctx.customer.customer_id, provider=provider
        )
        verification = await ai_provider_settings_service.get_verification_status(ctx.db, provider=provider)
        out.append(
            ProviderStatusOut(
                provider=provider,
                configured=is_provider_configured(provider, settings),
                enabled=enabled,
                verified_at=verification.last_verified_at if verification else None,
                verified_ok=verification.last_verified_ok if verification else None,
                verified_error=verification.last_error if verification else None,
            )
        )
    return out


@router.put("/v1/customers/{customer_id}/ai-providers/{provider}/enabled", response_model=ProviderStatusOut)
async def set_provider_enabled(
    provider: Provider,
    body: SetProviderEnabledRequest,
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> ProviderStatusOut:
    authorize_manage_ai_provider_settings(ctx.customer)
    await ai_provider_settings_service.set_provider_enabled_for_customer(
        ctx.db, customer_id=ctx.customer.customer_id, provider=provider, enabled=body.enabled
    )
    settings = get_settings()
    verification = await ai_provider_settings_service.get_verification_status(ctx.db, provider=provider)
    return ProviderStatusOut(
        provider=provider,
        configured=is_provider_configured(provider, settings),
        enabled=body.enabled,
        verified_at=verification.last_verified_at if verification else None,
        verified_ok=verification.last_verified_ok if verification else None,
        verified_error=verification.last_error if verification else None,
    )


@router.post(
    "/v1/customers/{customer_id}/ai-providers/{provider}/test-connection",
    response_model=TestProviderConnectionOut,
)
async def test_provider_connection(
    provider: Provider, ctx: CustomerRequestContext = Depends(get_customer_request_context)
) -> TestProviderConnectionOut:
    authorize_manage_ai_provider_settings(ctx.customer)
    settings = get_settings()
    ok, error_type, error_message = await ai_provider_settings_service.test_provider_connection(
        provider, settings
    )
    await ai_provider_settings_service.record_provider_verification(
        ctx.db, provider=provider, ok=ok, error_type=error_type, error_message=error_message
    )
    return TestProviderConnectionOut(provider=provider, ok=ok, error=error_message)


@router.get("/v1/customers/{customer_id}/ai-fallback", response_model=AIFallbackSettingOut)
async def get_fallback_setting(
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> AIFallbackSettingOut:
    """Any member can see whether automatic fallback is on — same
    "not sensitive the way a credential is" reasoning as the provider
    status list above."""
    enabled = await ai_provider_settings_service.is_fallback_enabled_for_customer(
        ctx.db, customer_id=ctx.customer.customer_id
    )
    return AIFallbackSettingOut(enabled=enabled)


@router.put("/v1/customers/{customer_id}/ai-fallback", response_model=AIFallbackSettingOut)
async def set_fallback_setting(
    body: SetAIFallbackSettingRequest, ctx: CustomerRequestContext = Depends(get_customer_request_context)
) -> AIFallbackSettingOut:
    authorize_manage_ai_provider_settings(ctx.customer)
    setting = await ai_provider_settings_service.set_fallback_enabled_for_customer(
        ctx.db, customer_id=ctx.customer.customer_id, enabled=body.enabled
    )
    return AIFallbackSettingOut(enabled=setting.enabled)


@router.get("/v1/customers/{customer_id}/me/ai-preference", response_model=AIPreferenceOut)
async def get_my_ai_preference(
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> AIPreferenceOut:
    pref = await ai_preference_service.get_user_ai_preference(
        ctx.db, customer_id=ctx.customer.customer_id, user_id=ctx.customer.user_id
    )
    if pref is None:
        return AIPreferenceOut(provider=None, model=None)
    return AIPreferenceOut(provider=Provider(pref.provider.value), model=pref.model)


@router.put("/v1/customers/{customer_id}/me/ai-preference", response_model=AIPreferenceOut)
async def set_my_ai_preference(
    body: SetAIPreferenceRequest, ctx: CustomerRequestContext = Depends(get_customer_request_context)
) -> AIPreferenceOut:
    pref = await ai_preference_service.set_user_ai_preference(
        ctx.db,
        customer_id=ctx.customer.customer_id,
        user_id=ctx.customer.user_id,
        provider=body.provider,
        model=body.model,
    )
    return AIPreferenceOut(provider=Provider(pref.provider.value), model=pref.model)


@router.delete("/v1/customers/{customer_id}/me/ai-preference", status_code=204)
async def clear_my_ai_preference(ctx: CustomerRequestContext = Depends(get_customer_request_context)) -> None:
    await ai_preference_service.clear_user_ai_preference(
        ctx.db, customer_id=ctx.customer.customer_id, user_id=ctx.customer.user_id
    )


@router.get("/v1/workspaces/{workspace_id}/ai-preference", response_model=AIPreferenceOut)
async def get_workspace_ai_preference(ctx: RequestContext = Depends(get_request_context)) -> AIPreferenceOut:
    authorize_use_chat(ctx.workspace)
    pref = await ai_preference_service.get_workspace_ai_preference(
        ctx.db, workspace_id=ctx.workspace.workspace_id
    )
    if pref is None:
        return AIPreferenceOut(provider=None, model=None)
    return AIPreferenceOut(provider=Provider(pref.provider.value), model=pref.model)


@router.put("/v1/workspaces/{workspace_id}/ai-preference", response_model=AIPreferenceOut)
async def set_workspace_ai_preference(
    body: SetAIPreferenceRequest, ctx: RequestContext = Depends(get_request_context)
) -> AIPreferenceOut:
    authorize_manage_workspace_ai_preference(ctx.workspace)
    pref = await ai_preference_service.set_workspace_ai_preference(
        ctx.db,
        workspace_id=ctx.workspace.workspace_id,
        customer_id=ctx.workspace.customer_id,
        provider=body.provider,
        model=body.model,
    )
    return AIPreferenceOut(provider=Provider(pref.provider.value), model=pref.model)


@router.delete("/v1/workspaces/{workspace_id}/ai-preference", status_code=204)
async def clear_workspace_ai_preference(ctx: RequestContext = Depends(get_request_context)) -> None:
    authorize_manage_workspace_ai_preference(ctx.workspace)
    await ai_preference_service.clear_workspace_ai_preference(ctx.db, workspace_id=ctx.workspace.workspace_id)
