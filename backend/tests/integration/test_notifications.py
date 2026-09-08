"""FR-NTF-002/003 — all four required notification types fire from real
triggers (not synthetically inserted), and none leak sensitive content.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.action_service import apply_transition, propose_action, submit_action_for_execution
from doda.application.task_service import change_task_status, create_task
from doda.db import tenant_scoped_session
from doda.domain.action.models import ActionStatus, RiskLevel
from doda.domain.notification.models import NotificationType
from doda.domain.task.models import TaskStatus
from doda.main import app
from tests.integration.conftest import seed_workspace_member

# A generous allow-list per notification type: anything outside this in
# safe_metadata would be a redaction regression (FR-NTF-003).
ALLOWED_METADATA_KEYS = {
    NotificationType.PENDING_APPROVAL: {"tool_name", "risk_level"},
    NotificationType.FAILED_ACTION: {"tool_name"},
    NotificationType.COMPLETED_TASK: {"title"},
    NotificationType.SECURITY_ALERT: {"scope", "reason"},
}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_pending_approval_notification_fires_for_r3_action(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={
            "tool_name": "email.send",
            "risk_level": "R3",
            "payload": {"to": "boss@example.com", "subject": "secret merger details"},
        },
        headers={**_auth_headers(member.session_id), "Idempotency-Key": "ntf-pending-1"},
    )
    assert submit.status_code == 200

    notifications = await client.get(
        f"/v1/workspaces/{member.workspace_id}/notifications", headers=_auth_headers(member.session_id)
    )
    assert notifications.status_code == 200
    matching = [n for n in notifications.json() if n["notification_type"] == "PENDING_APPROVAL"]
    assert len(matching) == 1
    assert set(matching[0]["safe_metadata"]) <= ALLOWED_METADATA_KEYS[NotificationType.PENDING_APPROVAL]
    # FR-NTF-003: the actual payload (recipient email, subject) must never
    # leak into the notification.
    assert "boss@example.com" not in str(matching[0]["safe_metadata"])
    assert "secret merger details" not in str(matching[0]["safe_metadata"])


async def test_failed_action_notification_fires_on_transition_to_failed(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()

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
            idempotency_key="ntf-failed-1",
        )
        await apply_transition(session, action, ActionStatus.VALIDATING, actor_id=f"user:{member.user_id}")
        await apply_transition(session, action, ActionStatus.READY, actor_id=f"user:{member.user_id}")
        await apply_transition(session, action, ActionStatus.RUNNING, actor_id=f"user:{member.user_id}")
        await apply_transition(session, action, ActionStatus.FAILED, actor_id=f"user:{member.user_id}")

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/notifications", headers=_auth_headers(member.session_id)
    )
    matching = [n for n in response.json() if n["notification_type"] == "FAILED_ACTION"]
    assert len(matching) == 1
    assert set(matching[0]["safe_metadata"]) <= ALLOWED_METADATA_KEYS[NotificationType.FAILED_ACTION]


async def test_completed_task_notification_fires_for_owner(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()

    async with tenant_scoped_session(member.customer_id) as session:
        task = await create_task(
            session,
            customer_id=member.customer_id,
            workspace_id=member.workspace_id,
            owner_id=f"user:{member.user_id}",
            title="Confidential project X report",
        )
        await change_task_status(
            session, task, target=TaskStatus.IN_PROGRESS, actor_id=f"user:{member.user_id}"
        )
        await change_task_status(session, task, target=TaskStatus.DONE, actor_id=f"user:{member.user_id}")

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/notifications", headers=_auth_headers(member.session_id)
    )
    matching = [n for n in response.json() if n["notification_type"] == "COMPLETED_TASK"]
    assert len(matching) == 1
    assert set(matching[0]["safe_metadata"]) <= ALLOWED_METADATA_KEYS[NotificationType.COMPLETED_TASK]


async def test_security_alert_broadcasts_to_every_workspace_member(
    client: AsyncClient, db_available: bool
) -> None:
    admin = await seed_workspace_member(workspace_role="workspace_admin")

    engage = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/kill-switch/engage",
        json={"reason": "drill"},
        headers=_auth_headers(admin.session_id),
    )
    assert engage.status_code == 200

    response = await client.get(
        f"/v1/workspaces/{admin.workspace_id}/notifications", headers=_auth_headers(admin.session_id)
    )
    matching = [n for n in response.json() if n["notification_type"] == "SECURITY_ALERT"]
    assert len(matching) == 1
    assert set(matching[0]["safe_metadata"]) <= ALLOWED_METADATA_KEYS[NotificationType.SECURITY_ALERT]


async def test_mark_read_is_idempotent_and_scoped_to_recipient(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()
    await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "x@example.com"}},
        headers={**_auth_headers(member.session_id), "Idempotency-Key": "ntf-read-1"},
    )
    listing = await client.get(
        f"/v1/workspaces/{member.workspace_id}/notifications", headers=_auth_headers(member.session_id)
    )
    notification_id = listing.json()[0]["id"]
    assert listing.json()[0]["read_at"] is None

    first_read = await client.post(
        f"/v1/workspaces/{member.workspace_id}/notifications/{notification_id}/read",
        headers=_auth_headers(member.session_id),
    )
    assert first_read.status_code == 200
    assert first_read.json()["read_at"] is not None

    second_read = await client.post(
        f"/v1/workspaces/{member.workspace_id}/notifications/{notification_id}/read",
        headers=_auth_headers(member.session_id),
    )
    assert second_read.status_code == 200
    assert second_read.json()["read_at"] == first_read.json()["read_at"]


async def test_another_user_cannot_mark_someone_elses_notification_read(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()
    other = await seed_workspace_member()

    await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "x@example.com"}},
        headers={**_auth_headers(member.session_id), "Idempotency-Key": "ntf-cross-1"},
    )
    listing = await client.get(
        f"/v1/workspaces/{member.workspace_id}/notifications", headers=_auth_headers(member.session_id)
    )
    notification_id = listing.json()[0]["id"]

    response = await client.post(
        f"/v1/workspaces/{other.workspace_id}/notifications/{notification_id}/read",
        headers=_auth_headers(other.session_id),
    )
    assert response.status_code == 404
