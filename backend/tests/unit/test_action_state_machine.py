import pytest

from doda.domain.action.models import ActionStatus
from doda.domain.action.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    InvalidActionTransition,
    is_terminal,
    transition,
)

VALID_PAIRS = [
    (ActionStatus.DRAFT, ActionStatus.VALIDATING),
    (ActionStatus.DRAFT, ActionStatus.CANCELLED),
    (ActionStatus.VALIDATING, ActionStatus.READY),
    (ActionStatus.VALIDATING, ActionStatus.AWAITING_APPROVAL),
    (ActionStatus.VALIDATING, ActionStatus.DENIED),
    (ActionStatus.AWAITING_APPROVAL, ActionStatus.READY),
    (ActionStatus.AWAITING_APPROVAL, ActionStatus.EXPIRED),
    (ActionStatus.AWAITING_APPROVAL, ActionStatus.REJECTED),
    (ActionStatus.READY, ActionStatus.RUNNING),
    (ActionStatus.READY, ActionStatus.CANCELLED),
    (ActionStatus.RUNNING, ActionStatus.SUCCEEDED),
    (ActionStatus.RUNNING, ActionStatus.FAILED),
    (ActionStatus.RUNNING, ActionStatus.COMPENSATING),
    (ActionStatus.FAILED, ActionStatus.RETRYING),
    (ActionStatus.RETRYING, ActionStatus.READY),
    (ActionStatus.COMPENSATING, ActionStatus.COMPENSATED),
    (ActionStatus.COMPENSATING, ActionStatus.FAILED),
]

INVALID_PAIRS = [
    (ActionStatus.DRAFT, ActionStatus.READY),  # skips VALIDATING
    (ActionStatus.DRAFT, ActionStatus.RUNNING),
    (ActionStatus.AWAITING_APPROVAL, ActionStatus.RUNNING),  # bypasses READY/approval
    (ActionStatus.RUNNING, ActionStatus.DRAFT),
    (ActionStatus.SUCCEEDED, ActionStatus.RUNNING),  # terminal, no escape
    (ActionStatus.DENIED, ActionStatus.READY),  # bypass attempt after deny
    (ActionStatus.CANCELLED, ActionStatus.RUNNING),
    (ActionStatus.EXPIRED, ActionStatus.READY),
]

NON_TERMINAL_STATUSES = [s for s in ActionStatus if s not in TERMINAL_STATUSES]


@pytest.mark.parametrize("current,target", VALID_PAIRS)
def test_allowed_transitions_succeed(current: ActionStatus, target: ActionStatus) -> None:
    assert transition(current, target) is target


@pytest.mark.parametrize("current,target", INVALID_PAIRS)
def test_disallowed_transitions_raise(current: ActionStatus, target: ActionStatus) -> None:
    with pytest.raises(InvalidActionTransition):
        transition(current, target)


def test_every_status_has_a_defined_fate() -> None:
    """Every ActionStatus is either a known origin (has outgoing edges) or a
    known terminal — none should silently fall through both sets, since that
    would mean an untested, undocumented dead end."""
    assert set(ActionStatus) <= set(ALLOWED_TRANSITIONS) | TERMINAL_STATUSES


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES, key=lambda s: s.value))
def test_terminal_statuses_are_reported_terminal(status: ActionStatus) -> None:
    assert is_terminal(status) is True


@pytest.mark.parametrize("status", NON_TERMINAL_STATUSES)
def test_non_terminal_statuses_are_not_reported_terminal(status: ActionStatus) -> None:
    assert is_terminal(status) is False
