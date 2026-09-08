import uuid

import pytest

from doda.application.authz_service import (
    AuthorizationError,
    WorkspaceContext,
    authorize_consume_approval,
    authorize_propose_action,
)
from doda.domain.action.models import Action, ActionStatus, RiskLevel
from doda.domain.identity.models import AuthStrength
from doda.domain.security.decisions import Decision
from doda.domain.security.roles import WorkspaceRole


def _context(role: WorkspaceRole, user_id: uuid.UUID | None = None) -> WorkspaceContext:
    return WorkspaceContext(
        customer_id=uuid.uuid4(), workspace_id=uuid.uuid4(), user_id=user_id or uuid.uuid4(), role=role
    )


def _action(actor_id: str) -> Action:
    return Action(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        tool_name="email.send",
        risk_level=RiskLevel.R3,
        payload={},
        payload_hash="deadbeef",
        idempotency_key="k",
        status=ActionStatus.AWAITING_APPROVAL,
    )


@pytest.mark.parametrize("role", [WorkspaceRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN])
def test_member_and_admin_may_propose_actions(role: WorkspaceRole) -> None:
    authorize_propose_action(_context(role))  # must not raise


def test_propose_action_has_no_role_left_unhandled() -> None:
    # WorkspaceRole only has two members today; this test is a tripwire so
    # that adding a third role forces a conscious decision here too.
    assert set(WorkspaceRole) == {WorkspaceRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN}


def test_self_approval_with_fresh_mfa_succeeds() -> None:
    user_id = uuid.uuid4()
    action = _action(actor_id=f"user:{user_id}")
    context = _context(WorkspaceRole.MEMBER, user_id=user_id)

    authorize_consume_approval(context, action, auth_strength=AuthStrength.AAL2)  # must not raise


def test_self_approval_without_fresh_mfa_requires_step_up() -> None:
    user_id = uuid.uuid4()
    action = _action(actor_id=f"user:{user_id}")
    context = _context(WorkspaceRole.MEMBER, user_id=user_id)

    with pytest.raises(AuthorizationError) as exc_info:
        authorize_consume_approval(context, action, auth_strength=AuthStrength.AAL1)
    assert exc_info.value.decision is Decision.STEP_UP_REQUIRED


def test_workspace_admin_may_approve_someone_elses_action() -> None:
    action = _action(actor_id=f"user:{uuid.uuid4()}")
    admin_context = _context(WorkspaceRole.WORKSPACE_ADMIN)

    authorize_consume_approval(admin_context, action, auth_strength=AuthStrength.AAL2)  # must not raise


def test_plain_member_may_not_approve_someone_elses_action() -> None:
    action = _action(actor_id=f"user:{uuid.uuid4()}")
    other_member_context = _context(WorkspaceRole.MEMBER)

    with pytest.raises(AuthorizationError) as exc_info:
        authorize_consume_approval(other_member_context, action, auth_strength=AuthStrength.AAL2)
    assert exc_info.value.decision is Decision.DENY
