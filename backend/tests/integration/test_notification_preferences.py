"""FR-NTF-004 — a recipient may turn off PENDING_APPROVAL/FAILED_ACTION/
COMPLETED_TASK, but SECURITY_ALERT must always fire regardless
("Security alert'ni o'chirib bo'lmaydi"). Proves both the service-layer
invariant and that a disabled preference actually suppresses the real
end-to-end trigger, not just a synthetic create_notification call.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.action_service import apply_transition, propose_action
from doda.application.notification_service import (
    NotificationPreferenceError,
    set_notification_preference,
)
from doda.db import tenant_scoped_session
from doda.domain.action.models import ActionStatus, RiskLevel
from doda.domain.notification.models import NotificationType
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_security_alert_preference_cannot_be_disabled(db_available: bool) -> None:
    member = await seed_workspace_member()
    async with tenant_scoped_session(member.customer_id) as session:
        with pytest.raises(NotificationPreferenceError):
            await set_notification_preference(
                session,
                customer_id=member.customer_id,
                recipient_id=f"user:{member.user_id}",
                notification_type=NotificationType.SECURITY_ALERT,
                enabled=False,
            )


async def test_default_preferences_are_all_enabled(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    response = await client.get(
        f"/v1/customers/{member.customer_id}/notification-preferences",
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 200
    resolved = {p["notification_type"]: p["enabled"] for p in response.json()}
    assert resolved == {
        "PENDING_APPROVAL": True,
        "FAILED_ACTION": True,
        "COMPLETED_TASK": True,
        "SECURITY_ALERT": True,
    }


async def test_disabling_security_alert_over_http_is_rejected(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()
    response = await client.put(
        f"/v1/customers/{member.customer_id}/notification-preferences/SECURITY_ALERT",
        json={"enabled": False},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SECURITY_ALERT_MANDATORY"


async def test_disabling_a_type_persists_and_suppresses_the_real_trigger(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()

    disable_response = await client.put(
        f"/v1/customers/{member.customer_id}/notification-preferences/FAILED_ACTION",
        json={"enabled": False},
        headers=_auth_headers(member.session_id),
    )
    assert disable_response.status_code == 200
    assert disable_response.json() == {"notification_type": "FAILED_ACTION", "enabled": False}

    listed = await client.get(
        f"/v1/customers/{member.customer_id}/notification-preferences",
        headers=_auth_headers(member.session_id),
    )
    resolved = {p["notification_type"]: p["enabled"] for p in listed.json()}
    assert resolved["FAILED_ACTION"] is False
    assert resolved["COMPLETED_TASK"] is True  # untouched types stay enabled

    # Same real trigger as test_notifications.py's
    # test_failed_action_notification_fires_on_transition_to_failed — this
    # time it must produce NOTHING.
    async with tenant_scoped_session(member.customer_id) as session:
        action, _ = await propose_action(
            session,
            customer_id=member.customer_id,
            workspace_id=member.workspace_id,
            trace_id=uuid.uuid4(),
            actor_id=f"user:{member.user_id}",
            tool_name="calendar.create_event",
            risk_level=RiskLevel.R1,
            payload={},
            idempotency_key="ntf-pref-suppressed-1",
        )
        await apply_transition(session, action, ActionStatus.VALIDATING, actor_id=f"user:{member.user_id}")
        await apply_transition(session, action, ActionStatus.READY, actor_id=f"user:{member.user_id}")
        await apply_transition(session, action, ActionStatus.RUNNING, actor_id=f"user:{member.user_id}")
        await apply_transition(session, action, ActionStatus.FAILED, actor_id=f"user:{member.user_id}")

    notifications = await client.get(
        f"/v1/workspaces/{member.workspace_id}/notifications", headers=_auth_headers(member.session_id)
    )
    matching = [n for n in notifications.json() if n["notification_type"] == "FAILED_ACTION"]
    assert matching == []


async def test_re_enabling_a_disabled_type_updates_the_existing_row(
    client: AsyncClient, db_available: bool
) -> None:
    """The toggle the frontend actually offers: off, then back on. Every
    existing test only ever created a preference row for the first time, so
    set_notification_preference's update branch — the one that mutates a row
    that is already there — had no coverage, and the notification it controls
    is the thing being switched back on."""
    member = await seed_workspace_member()
    url = f"/v1/customers/{member.customer_id}/notification-preferences/COMPLETED_TASK"

    off = await client.put(url, json={"enabled": False}, headers=_auth_headers(member.session_id))
    assert off.json() == {"notification_type": "COMPLETED_TASK", "enabled": False}

    on = await client.put(url, json={"enabled": True}, headers=_auth_headers(member.session_id))
    assert on.status_code == 200
    assert on.json() == {"notification_type": "COMPLETED_TASK", "enabled": True}

    listed = await client.get(
        f"/v1/customers/{member.customer_id}/notification-preferences",
        headers=_auth_headers(member.session_id),
    )
    resolved = {p["notification_type"]: p["enabled"] for p in listed.json()}
    assert resolved["COMPLETED_TASK"] is True

    # And the real trigger fires again, rather than the re-enable being a
    # row that reads "enabled" while create_notification still suppresses it.
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Re-enabled task"},
        headers=_auth_headers(member.session_id),
    )
    task_id = create.json()["id"]
    for status in ("IN_PROGRESS", "DONE"):
        transition = await client.post(
            f"/v1/workspaces/{member.workspace_id}/tasks/{task_id}/status",
            json={"target_status": status},
            headers=_auth_headers(member.session_id),
        )
        assert transition.status_code == 200

    notifications = await client.get(
        f"/v1/workspaces/{member.workspace_id}/notifications", headers=_auth_headers(member.session_id)
    )
    assert [n for n in notifications.json() if n["notification_type"] == "COMPLETED_TASK"]
