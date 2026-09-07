"""Action state machine — TRD section 4.2, authoritative.

This module is pure (no I/O, no session) so it can be unit-tested without a
database. The application layer is responsible for persisting the result
and for auditing rejected attempts (4.2: "ruxsat etilmagan o'tish urinishi
xato sifatida yoziladi va audit qilinadi") — see
doda.application.action_service.apply_transition.
"""

from doda.domain.action.models import ActionStatus

ALLOWED_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.DRAFT: frozenset({ActionStatus.VALIDATING, ActionStatus.CANCELLED}),
    ActionStatus.VALIDATING: frozenset(
        {ActionStatus.AWAITING_APPROVAL, ActionStatus.READY, ActionStatus.DENIED}
    ),
    ActionStatus.AWAITING_APPROVAL: frozenset(
        {ActionStatus.READY, ActionStatus.EXPIRED, ActionStatus.REJECTED}
    ),
    ActionStatus.READY: frozenset({ActionStatus.RUNNING, ActionStatus.CANCELLED}),
    ActionStatus.RUNNING: frozenset(
        {ActionStatus.SUCCEEDED, ActionStatus.FAILED, ActionStatus.COMPENSATING}
    ),
    # The TRD table lists FAILED's next state as "RETRYING / Terminal": it
    # may be retried (modeled here as FAILED -> RETRYING -> READY) or it may
    # simply remain FAILED if nothing calls transition() again — that is why
    # FAILED has an outgoing edge yet is also in TERMINAL_STATUSES below.
    ActionStatus.FAILED: frozenset({ActionStatus.RETRYING}),
    ActionStatus.RETRYING: frozenset({ActionStatus.READY}),
    ActionStatus.COMPENSATING: frozenset({ActionStatus.COMPENSATED, ActionStatus.FAILED}),
}

TERMINAL_STATUSES: frozenset[ActionStatus] = frozenset(
    {
        ActionStatus.SUCCEEDED,
        ActionStatus.COMPENSATED,
        ActionStatus.DENIED,
        ActionStatus.REJECTED,
        ActionStatus.EXPIRED,
        ActionStatus.CANCELLED,
        ActionStatus.FAILED,
    }
)


class InvalidActionTransition(Exception):
    def __init__(self, current: ActionStatus, target: ActionStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"{current.value} -> {target.value} is not an allowed action transition (TRD 4.2)")


def transition(current: ActionStatus, target: ActionStatus) -> ActionStatus:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidActionTransition(current, target)
    return target


def is_terminal(status: ActionStatus) -> bool:
    return status in TERMINAL_STATUSES
