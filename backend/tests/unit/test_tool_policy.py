"""OD-002 / the security-review finding recorded in CLAUDE.md and
ADR-007: a caller must not be able to under-declare risk_level for a
tool that has a registered minimum. Pure domain logic, no DB needed.
"""

from doda.domain.action.models import RiskLevel
from doda.domain.action.tool_policy import TOOL_MINIMUM_RISK_LEVEL, enforce_minimum_risk_level


def test_registered_tool_below_minimum_is_raised_to_the_minimum() -> None:
    assert enforce_minimum_risk_level("telegram.send_message", RiskLevel.R0) is RiskLevel.R3


def test_registered_tool_at_minimum_is_unchanged() -> None:
    assert enforce_minimum_risk_level("telegram.send_message", RiskLevel.R3) is RiskLevel.R3


def test_registered_tool_above_minimum_is_honored_not_lowered() -> None:
    assert enforce_minimum_risk_level("telegram.send_message", RiskLevel.R5) is RiskLevel.R5


def test_unregistered_tool_name_is_unaffected() -> None:
    # No connector/registry entry exists for this tool_name — caller's
    # requested level passes through exactly as before this module
    # existed, deliberately (see module docstring: this is not the full
    # FR-ACT-001 allowlist).
    assert enforce_minimum_risk_level("some.future.tool", RiskLevel.R0) is RiskLevel.R0


def test_telegram_send_message_is_registered_at_r3() -> None:
    # Pins the actual policy decision (OD-002), not just the mechanism —
    # a change to this value should be a conscious, reviewed edit.
    assert TOOL_MINIMUM_RISK_LEVEL["telegram.send_message"] is RiskLevel.R3
