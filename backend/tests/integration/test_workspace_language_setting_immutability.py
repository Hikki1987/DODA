"""FR-WKS-007's own acceptance criterion ("Sozlama o'zgarishi
versiylanadi") is asserted directly here, not just observed — same
discipline as test_task_decisions_reject_update_and_delete and
test_audit_events_reject_update_and_delete. Without this test, a
migration that dropped 0021's trigger (or a downgrade that left it off)
would take the whole append-only guarantee with it and nothing else
would notice, since no other test attempts an UPDATE/DELETE."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from doda.application.workspace_service import create_workspace, set_workspace_language
from doda.db import tenant_scoped_session
from doda.domain.workspace.models import WorkspaceLanguageSetting


async def test_workspace_language_settings_reject_update_and_delete(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        workspace = await create_workspace(session, customer_id=customer_id, name="Test Workspace")
        setting = await set_workspace_language(
            session,
            customer_id=customer_id,
            workspace_id=workspace.id,
            actor_id="user:writer",
            language="UZ",
        )
        setting_id = setting.id

    for statement, operation in (
        (text("UPDATE workspace_language_settings SET language = 'RU' WHERE id = :id"), "UPDATE"),
        (text("DELETE FROM workspace_language_settings WHERE id = :id"), "DELETE"),
    ):
        async with tenant_scoped_session(customer_id) as session:
            with pytest.raises(DBAPIError) as excinfo:
                await session.execute(statement, {"id": setting_id})
            assert "append-only" in str(excinfo.value), f"{operation} must be refused by the trigger"

    async with tenant_scoped_session(customer_id) as session:
        survivor = await session.get(WorkspaceLanguageSetting, setting_id)
        assert survivor is not None
        assert survivor.language == "UZ"
