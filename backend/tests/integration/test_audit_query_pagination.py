"""list_audit_events' cursor pagination (11.2: "Pagination cursor asosida")
against a live Postgres — the `before_id` keyset-comparison code path had
no test at all until this file (found while cleaning up a mypy warning on
that exact line)."""

import uuid

from doda.application.audit_query_service import list_audit_events
from doda.application.audit_service import record_audit_event

TOTAL_EVENTS = 5


async def test_before_id_cursor_returns_strictly_older_events_without_gaps_or_dupes(
    tenant_session,
) -> None:
    customer_id, session = tenant_session
    trace_id = uuid.uuid4()

    created_ids = []
    for i in range(TOTAL_EVENTS):
        event = await record_audit_event(
            session,
            customer_id=customer_id,
            trace_id=trace_id,
            actor_id="user:pagination-test",
            event_type=f"test.paginated.{i}.v1",
        )
        created_ids.append(event.id)

    first_page = await list_audit_events(session, customer_id=customer_id, limit=2)
    assert len(first_page) == 2
    assert [e.id for e in first_page] == list(reversed(created_ids))[:2]

    second_page = await list_audit_events(
        session, customer_id=customer_id, limit=2, before_id=first_page[-1].id
    )
    assert len(second_page) == 2

    third_page = await list_audit_events(
        session, customer_id=customer_id, limit=2, before_id=second_page[-1].id
    )
    assert len(third_page) == 1

    all_pages_ids = [e.id for e in first_page] + [e.id for e in second_page] + [e.id for e in third_page]
    assert all_pages_ids == list(reversed(created_ids))  # no gaps, no duplicates, correct order


async def test_before_id_referencing_an_unknown_event_is_ignored_not_an_error(tenant_session) -> None:
    """A stale/foreign cursor id must not blow up the request — just fall
    back to an unfiltered first page (session.get returns None, the where
    clause is simply skipped)."""
    customer_id, session = tenant_session
    await record_audit_event(
        session,
        customer_id=customer_id,
        trace_id=uuid.uuid4(),
        actor_id="user:pagination-test",
        event_type="test.solo.v1",
    )

    events = await list_audit_events(session, customer_id=customer_id, before_id=uuid.uuid4())
    assert len(events) == 1
