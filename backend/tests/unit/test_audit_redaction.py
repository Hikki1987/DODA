"""FR-AUD-003 (Must): "Audit yozuvida secret, token, PII yoki prompt
kontenti bo'lmaydi" — acceptance criterion is "Redaction scanner CI'da 0
topilma" (a redaction scanner in CI, zero findings). Static AST check, no
DB needed — same approach as test_domain_isolation.py: every
record_audit_event(...) call site's safe_metadata= literal is parsed, and
its keys are checked against a single, hand-reviewed allowlist. A future
call site that accidentally passes something like `"email": user.email`
or `"password": token` fails this test immediately, rather than silently
writing it into the append-only audit trail — which, per the
audit_events_no_update_delete trigger (0001-migration), can then never be
corrected after the fact.

This does not — and cannot, statically — verify that the two free-text
VALUES already on the allowlist (`reason`, `name`) never contain
something sensitive a human typed in; that is an inherent, accepted
tradeoff of those fields existing at all (a kill-switch engage reason or
a workspace name is only useful in an audit trail if it stays
human-readable). What this test DOES guarantee: no new field name can be
added to any audit event without a reviewer consciously adding it here
first, after confirming it cannot carry a secret/token/PII/prompt value.
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).parents[2] / "src" / "doda"

# Every key ever passed to record_audit_event(safe_metadata=...) as of
# this writing, reviewed and accepted: internal identifiers/UUIDs, enum
# values, counts, and the two free-text fields discussed in the module
# docstring above (`name`, `reason`).
ALLOWED_SAFE_METADATA_KEYS = {
    "scope",
    "result_count",
    "event_type_filter",
    "role",
    "checked_count",
    "violation_count",
    "action_id",
    "tool_name",
    "risk_level",
    "from",
    "to",
    "from_role",
    "to_role",
    "customer_id",
    "customer_membership_id",
    "workspace_id",
    "workspace_membership_id",
    "name",
    "reason",
    "notification_id",
    "recipient_id",
    "notification_type",
    "reference_type",
    "reference_id",
}


def _record_audit_event_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "record_audit_event"
    ]


def _safe_metadata_keys(call: ast.Call, py_file: Path) -> set[str] | None:
    """The literal string keys of one call's safe_metadata= argument, or
    None if the call passed no safe_metadata kwarg at all (defaults to {}
    in record_audit_event's own signature, which is trivially safe)."""
    for kw in call.keywords:
        if kw.arg != "safe_metadata":
            continue
        if not isinstance(kw.value, ast.Dict):
            raise AssertionError(
                f"{py_file}:{call.lineno}: record_audit_event(...) passes safe_metadata as "
                "something other than a literal dict — this test can only statically verify "
                "dict literals; rewrite it as one, or extend this test to handle the new shape."
            )
        keys = set()
        for key_node in kw.value.keys:
            if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
                raise AssertionError(
                    f"{py_file}:{call.lineno}: record_audit_event(...) safe_metadata has a "
                    "non-literal-string key — this test can only statically verify plain "
                    "string keys."
                )
            keys.add(key_node.value)
        return keys
    return None


def test_every_audit_event_safe_metadata_key_is_on_the_reviewed_allowlist() -> None:
    py_files = list(SRC_ROOT.rglob("*.py"))
    assert py_files, "expected at least one source file under src/doda"

    violations = []
    call_sites_checked = 0
    for py_file in py_files:
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for call in _record_audit_event_calls(tree):
            call_sites_checked += 1
            keys = _safe_metadata_keys(call, py_file)
            if keys is None:
                continue
            unknown = keys - ALLOWED_SAFE_METADATA_KEYS
            if unknown:
                violations.append(
                    f"{py_file.relative_to(SRC_ROOT)}:{call.lineno} passes unreviewed "
                    f"safe_metadata key(s) {sorted(unknown)} — add to ALLOWED_SAFE_METADATA_KEYS "
                    "only after confirming the value cannot be a secret, token, PII, or "
                    "prompt/LLM content (FR-AUD-003)."
                )

    # A zero call-site count would mean this test silently checks nothing —
    # the exact class of bug test_rls_coverage.py's own first version had
    # (see CLAUDE.md) before it was made to import every domain explicitly.
    assert call_sites_checked > 0, (
        "found zero record_audit_event(...) call sites — has the import path changed away "
        "from the bare `record_audit_event` name this test's AST matcher looks for?"
    )
    assert not violations, "FR-AUD-003 redaction scanner finding(s):\n" + "\n".join(violations)
