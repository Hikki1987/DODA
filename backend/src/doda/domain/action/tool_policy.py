"""Tool -> minimum risk level policy (FR-ACT-001, partial). A security
review of this branch (see CLAUDE.md) found `risk_level` on a proposed
Action was entirely caller-supplied: without a server-side floor, a
member could declare a sensitive tool call as R0 and skip approval/
step-up (9.1) entirely. At the time this was flagged, it wasn't yet
dangerous because no connector existed to act on a READY Action.

OD-002 (first connector = Telegram, Product Owner decision) made that
real: `infrastructure/telegram_relay.py` now actually consumes READY
`telegram.send_message` Actions and calls the real Telegram Bot API, so
this module's floor for that one tool is a live mitigation, not a
preemptive one. Any future connector for a tool NOT registered here
would reopen the same caller-under-declared-risk gap for that tool —
see this module's own registration note below.

This is deliberately NOT the full tool registry FR-ACT-001 describes (an
allowlist that rejects any unregistered tool_name outright) — most
tool_name values used in this codebase today (in tests, and by any
future caller) are placeholders for a connector ecosystem that mostly
doesn't exist yet, so rejecting unregistered names now would be a much
larger, speculative change. An unregistered tool_name's caller-supplied
risk_level is honored as-is, unchanged from before this module existed.
Add an entry here only once a tool is backed by a real connector and its
minimum risk has actually been reviewed — never speculatively.
"""

from doda.domain.action.models import RiskLevel

_RISK_ORDER: dict[RiskLevel, int] = {level: index for index, level in enumerate(RiskLevel)}

TOOL_MINIMUM_RISK_LEVEL: dict[str, RiskLevel] = {
    # OD-002: sending a message to a real person via Telegram is a
    # meaningful, hard-to-undo external side effect — same tier as the
    # send_email/email.send precedent already used throughout the test
    # suite for exactly this reason.
    "telegram.send_message": RiskLevel.R3,
}


def enforce_minimum_risk_level(tool_name: str, requested: RiskLevel) -> RiskLevel:
    """The risk level to actually use for a proposal: `requested`, raised
    to the tool's registered minimum if one exists and `requested` was
    below it. Never lowers a caller's request — asking for a tier ABOVE
    the minimum (e.g. R4 for a registered R3 tool) is honored as-is."""
    minimum = TOOL_MINIMUM_RISK_LEVEL.get(tool_name)
    if minimum is None:
        return requested
    return requested if _RISK_ORDER[requested] >= _RISK_ORDER[minimum] else minimum
