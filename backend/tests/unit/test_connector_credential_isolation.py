"""FR-ACT-006 (Must): "Connector credential hech qachon model kontekstiga
uzatilmaydi" — acceptance: "Prompt/audit/log'da token qidiruvi 0 natija
beradi" (searching for the token in prompt/audit/log turns up 0 hits).

Static text scan, no DB needed — same approach as
test_audit_redaction.py, test_bootstrap_index_writers.py and
test_side_effect_boundary.py: verify a security invariant by inspecting
the source, not by hoping a human remembers it on every future change.

Today's only connector credential is `Settings.telegram_bot_token`
(config.py) — its only two legitimate references are its own
declaration and infrastructure/telegram_relay.py, which unwraps it
exactly once, right before crossing into telegram_client.send_message's
plain-str signature (see that file's own comment for why it stays
wrapped until there). This is checked across the WHOLE codebase, not
just the AI/prompt layer (doda/ai/*, application/ai_tools.py,
application/conversation_service.py) — a leak into an unrelated log
helper or API handler is just as real a violation of "the token never
appears in a prompt/audit/log" as a leak into the AI layer specifically,
and scanning everything is simpler than trying to enumerate "the AI
layer" as a separate, parallel-maintained file list.

Deliberately narrower than FR-ACT-006's own name suggests ("connector
credential", singular precedent for whatever the next connector adds):
CONNECTOR_CREDENTIAL_FIELD_NAMES is an explicit, reviewed list, not a
pattern match on `config.py` field names — a second connector's own
credential field is NOT automatically covered until it is added here
too. That is a conscious tradeoff (an explicit list that must be
updated beats a clever heuristic that silently stops matching),
documented so it is not mistaken for an oversight later.
"""

from pathlib import Path

SRC_ROOT = Path(__file__).parents[2] / "src" / "doda"

CONNECTOR_CREDENTIAL_FIELD_NAMES = {"telegram_bot_token"}

# Files allowed to reference a connector credential field name at all.
ALLOWED_FILES = {
    SRC_ROOT / "config.py",  # the field's own declaration
    SRC_ROOT / "infrastructure" / "telegram_relay.py",  # unwraps it once, for its own connector call
}


def test_no_connector_credential_field_name_appears_outside_its_own_connector() -> None:
    py_files = [p for p in SRC_ROOT.rglob("*.py") if p not in ALLOWED_FILES]
    assert py_files, "expected at least one source file under src/doda"

    violations = []
    for py_file in py_files:
        source = py_file.read_text()
        for name in CONNECTOR_CREDENTIAL_FIELD_NAMES:
            if name in source:
                violations.append(f"{py_file.relative_to(SRC_ROOT)} references {name!r}")

    assert not violations, (
        "FR-ACT-006 violation(s) — a connector credential referenced outside its own connector:\n"
        + "\n".join(violations)
    )
