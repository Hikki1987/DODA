"""The input-handling edges every endpoint shares, none of which had a test:
a malformed bearer token, an unknown workspace id, and a client-supplied
X-Trace-Id that isn't a UUID.

Each is a documented behaviour rather than an accident of the code —
_parse_bearer_session_id converts an unparseable token into the same
SessionInvalidError as a missing one; _resolve_request_context answers an
unknown workspace id with DENY specifically so existence is not leaked (10.1);
TraceIdMiddleware says in so many words that a non-UUID value is "replaced,
not rejected" so the trace id can double as an Action's. Coverage showed all
three lines unexecuted, which means each claim rested on reading the code.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.api.middleware import TRACE_ID_HEADER
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_a_malformed_bearer_token_is_rejected_as_unauthenticated(
    client: AsyncClient, db_available: bool
) -> None:
    """ "Bearer not-a-uuid" must land on the same 401 as no header at all —
    not a 422 from path parsing and not a 500 from uuid.UUID raising."""
    member = await seed_workspace_member()

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        headers={"Authorization": "Bearer not-a-uuid"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_an_unknown_workspace_id_is_denied_not_reported_as_missing(
    client: AsyncClient, db_available: bool
) -> None:
    """A workspace id with no WorkspaceTenantIndex row at all: 403 DENY, the
    same answer a real workspace the caller has no membership in gives, so
    the two cannot be told apart (10.1)."""
    member = await seed_workspace_member()

    response = await client.get(
        f"/v1/workspaces/{uuid.uuid4()}/tasks",
        headers={"Authorization": f"Bearer {member.session_id}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_a_non_uuid_trace_id_header_is_replaced_rather_than_rejected(
    client: AsyncClient, db_available: bool
) -> None:
    """TraceIdMiddleware's documented contract for junk input: the request
    still succeeds, and the trace id it reports back is a real UUID (so it can
    still be an Action's trace_id) rather than the client's string echoed."""
    member = await seed_workspace_member()

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        headers={
            "Authorization": f"Bearer {member.session_id}",
            TRACE_ID_HEADER: "definitely-not-a-uuid",
        },
    )
    assert response.status_code == 200
    returned = response.headers[TRACE_ID_HEADER]
    assert returned != "definitely-not-a-uuid"
    uuid.UUID(returned)  # raises if the replacement isn't a real UUID
