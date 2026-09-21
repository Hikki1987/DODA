"""End-to-end HTTP tests for the knowledge/file API — FR-KNW-001. Same
authoritative-chain pattern as test_tasks_api.py. Storage is pointed at
a per-test tmp_path (doda.api.knowledge.get_settings monkeypatched) so
tests never touch the real ./data/knowledge directory or share state
across test runs.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.config import Settings
from doda.main import app
from tests.integration.conftest import seed_workspace_member

_REAL_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nreal pdf body here"
_WINDOWS_PE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00this is really an executable"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(knowledge_storage_dir=str(tmp_path))  # type: ignore[arg-type]
    monkeypatch.setattr("doda.api.knowledge.get_settings", lambda: settings)
    return settings


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


def _upload_files(filename: str, content_type: str, data: bytes) -> dict:
    return {"file": (filename, data, content_type)}


async def test_missing_session_is_rejected(
    client: AsyncClient, db_available: bool, storage_settings: Settings
) -> None:
    member = await seed_workspace_member()
    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/documents",
        files=_upload_files("report.pdf", "application/pdf", _REAL_PDF_BYTES),
    )
    assert response.status_code == 401


async def test_no_membership_is_denied(
    client: AsyncClient, db_available: bool, storage_settings: Settings
) -> None:
    member = await seed_workspace_member()
    other = await seed_workspace_member()
    response = await client.post(
        f"/v1/workspaces/{other.workspace_id}/documents",
        files=_upload_files("report.pdf", "application/pdf", _REAL_PDF_BYTES),
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_member_can_upload_list_get_and_download_a_document(
    client: AsyncClient, db_available: bool, storage_settings: Settings
) -> None:
    member = await seed_workspace_member()

    upload = await client.post(
        f"/v1/workspaces/{member.workspace_id}/documents",
        files=_upload_files("report.pdf", "application/pdf", _REAL_PDF_BYTES),
        headers=_auth_headers(member.session_id),
    )
    assert upload.status_code == 200
    document = upload.json()
    assert document["filename"] == "report.pdf"
    assert document["content_type"] == "application/pdf"
    assert document["size_bytes"] == len(_REAL_PDF_BYTES)
    assert document["uploader_id"] == f"user:{member.user_id}"

    listing = await client.get(
        f"/v1/workspaces/{member.workspace_id}/documents", headers=_auth_headers(member.session_id)
    )
    assert listing.status_code == 200
    assert [d["id"] for d in listing.json()] == [document["id"]]

    get_one = await client.get(
        f"/v1/workspaces/{member.workspace_id}/documents/{document['id']}",
        headers=_auth_headers(member.session_id),
    )
    assert get_one.status_code == 200

    download = await client.get(
        f"/v1/workspaces/{member.workspace_id}/documents/{document['id']}/content",
        headers=_auth_headers(member.session_id),
    )
    assert download.status_code == 200
    assert download.content == _REAL_PDF_BYTES
    assert download.headers["content-type"] == "application/pdf"


async def test_a_malicious_file_disguised_as_a_pdf_is_rejected_and_never_stored(
    client: AsyncClient, db_available: bool, storage_settings: Settings
) -> None:
    """The security-test acceptance criterion, exercised over the real
    HTTP API rather than just the validator's own unit test: a Windows
    executable declared as application/pdf is refused with 422 and no
    Document row is ever created."""
    member = await seed_workspace_member()

    upload = await client.post(
        f"/v1/workspaces/{member.workspace_id}/documents",
        files=_upload_files("invoice.pdf", "application/pdf", _WINDOWS_PE_BYTES),
        headers=_auth_headers(member.session_id),
    )
    assert upload.status_code == 422
    assert upload.json()["code"] == "INVALID_FILE"

    listing = await client.get(
        f"/v1/workspaces/{member.workspace_id}/documents", headers=_auth_headers(member.session_id)
    )
    assert listing.json() == []


async def test_owner_can_delete_their_own_upload(
    client: AsyncClient, db_available: bool, storage_settings: Settings
) -> None:
    member = await seed_workspace_member()
    upload = await client.post(
        f"/v1/workspaces/{member.workspace_id}/documents",
        files=_upload_files("report.pdf", "application/pdf", _REAL_PDF_BYTES),
        headers=_auth_headers(member.session_id),
    )
    document_id = upload.json()["id"]

    delete = await client.delete(
        f"/v1/workspaces/{member.workspace_id}/documents/{document_id}",
        headers=_auth_headers(member.session_id),
    )
    assert delete.status_code == 204

    get_after_delete = await client.get(
        f"/v1/workspaces/{member.workspace_id}/documents/{document_id}",
        headers=_auth_headers(member.session_id),
    )
    assert get_after_delete.status_code == 404
