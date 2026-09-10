"""6.2's dependency rule "every external side effect goes through outbox +
idempotency", enforced statically — the same AST approach as
test_domain_isolation.py, and for the same reason: CLAUDE.md says these
dependency rules are checked in CI, and until now only two of them actually
were (domain isolation and RLS coverage).

The enforceable shape of the rule is a layering one: nothing outside the
infrastructure layer may speak to the outside world directly. An API handler
or application service that called an external API itself would bypass the
whole chain the architecture is built on — approval, idempotency key, outbox
row, audit trail, and the state machine that records RUNNING/SUCCEEDED — and
no amount of downstream checking could undo a request already sent.

It holds today (only telegram_client.py and telegram_relay.py import httpx)
and the point is to keep it holding as more connectors arrive: the next one
has to be placed behind the relay, not wired into a request handler, and this
test is what says so before the code review does.
"""

import ast
import pathlib

SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "doda"

# Libraries that reach the network on their own behalf. Redis is deliberately
# NOT here: it is the outbox's own transport (ADR-003), not an external side
# effect, and the relay workers that use it already live in infrastructure/.
OUTBOUND_CLIENT_MODULES = {"httpx", "requests", "urllib.request", "aiohttp"}

# Only the layer whose job is talking to the outside world, and only the
# modules within it that exist for that purpose. Adding an entry here means
# accepting a new place that can produce an un-audited external effect.
ALLOWED = {
    "infrastructure/telegram_client.py",  # the Bot API client itself
    "infrastructure/telegram_relay.py",  # drives it from the outbox stream
}


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
    return modules


def test_only_the_infrastructure_layer_may_make_outbound_calls() -> None:
    violations: list[str] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT).as_posix()
        if relative in ALLOWED:
            continue
        imported = _imported_modules(ast.parse(path.read_text()))
        for module in sorted(imported):
            root = module.split(".")[0]
            if module in OUTBOUND_CLIENT_MODULES or root in OUTBOUND_CLIENT_MODULES:
                violations.append(f"{relative} imports {module}")

    assert violations == [], (
        "an outbound HTTP client is reachable outside the infrastructure layer: "
        + "; ".join(violations)
        + ". Every external side effect must go through approval -> idempotency -> outbox -> "
        "relay (6.2), because a request already sent cannot be un-sent."
    )
