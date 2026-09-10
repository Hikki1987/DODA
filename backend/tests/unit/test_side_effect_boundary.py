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

# Libraries that reach the network on their own behalf. Redis is handled
# separately below: it is the outbox's own transport (ADR-003), not an
# external side effect, but it has a layering rule of its own.
OUTBOUND_CLIENT_MODULES = {"httpx", "requests", "urllib.request", "aiohttp"}

# The broker may only be touched by the workers that drain the outbox, plus
# config (which merely holds its URL). The request path must reach Redis
# only indirectly, by committing an outbox row — that is the entire point of
# a transactional outbox: publishing from a handler would either emit a
# message before its transaction commits, or lose it when that transaction
# rolls back, and no consumer could tell the difference.
BROKER_MODULES = {"redis"}
BROKER_ALLOWED = {
    "config.py",  # holds redis_url; opens no connection
    "infrastructure/outbox_relay.py",  # drains the outbox into the stream
    "infrastructure/telegram_relay.py",  # consumes that stream
}

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


def _forbidden_imports(banned_modules: set[str], allowed_files: set[str]) -> list[str]:
    """Shared mechanism behind both tests below: "this module set may only
    be imported from this file allowlist." Each test supplies its own
    banned set and allowlist — the two rules stay independently named and
    documented (they protect different properties, see each test's own
    docstring), only the walk-and-match loop itself is shared.

    A dotted import (`redis.asyncio`) is matched by its root package
    (`redis`), not just an exact set membership — `httpx.AsyncClient`-style
    submodule imports need this, and it's a strict superset of "exact
    match only", so sharing it changes neither test's result.
    """
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT).as_posix()
        if relative in allowed_files:
            continue
        imported = _imported_modules(ast.parse(path.read_text()))
        for module in sorted(imported):
            root = module.split(".")[0]
            if module in banned_modules or root in banned_modules:
                violations.append(f"{relative} imports {module}")
    return violations


def test_only_the_infrastructure_layer_may_make_outbound_calls() -> None:
    violations = _forbidden_imports(OUTBOUND_CLIENT_MODULES, ALLOWED)

    assert violations == [], (
        "an outbound HTTP client is reachable outside the infrastructure layer: "
        + "; ".join(violations)
        + ". Every external side effect must go through approval -> idempotency -> outbox -> "
        "relay (6.2), because a request already sent cannot be un-sent."
    )


def test_only_the_outbox_workers_may_talk_to_the_broker() -> None:
    """ADR-003's transactional-outbox guarantee, as a layering rule.

    Deliberately separate from the test above: Redis is not an external side
    effect, so it is not banned outside infrastructure/ for that reason. The
    reason here is atomicity — an API handler or application service that
    published to the stream itself would break the one property the outbox
    exists to provide, that a message is visible exactly when (and only when)
    its database transaction committed.

    This also happens to pin a resilience property worth stating: nothing on
    the request path imports the broker at all, so the API does not need Redis
    to be up in order to accept work — it writes a row, and the worker
    publishes later.
    """
    violations = _forbidden_imports(BROKER_MODULES, BROKER_ALLOWED)

    assert violations == [], (
        "the broker is reachable outside the outbox workers: "
        + "; ".join(violations)
        + ". Publish by committing an outbox row instead (ADR-003) — a message "
        "emitted from the request path is either premature or lost on rollback."
    )
