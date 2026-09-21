"""Knowledge/file endpoints — FR-KNW-001 only. Same authoritative-chain
pattern as api/tasks.py: every handler gets its tenant/authz context only
from RequestContext, never from client-supplied customer_id/actor_id.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response

from doda.api.dependencies import RequestContext, get_request_context
from doda.api.knowledge_schemas import DocumentOut
from doda.application.authz_service import authorize_use_knowledge
from doda.application.knowledge_service import delete_document, ingest_file, list_documents_for_workspace
from doda.config import get_settings
from doda.domain.knowledge.models import Document
from doda.storage.factory import get_object_storage
from doda.storage.port import ObjectNotFoundError

router = APIRouter(tags=["knowledge"])


def _to_document_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        workspace_id=document.workspace_id,
        uploader_id=document.uploader_id,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        created_at=document.created_at,
    )


async def _get_owned_document(ctx: RequestContext, document_id: uuid.UUID) -> Document:
    document = await ctx.db.get(Document, document_id)
    if document is None or document.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="document not found")
    return document


@router.post("/v1/workspaces/{workspace_id}/documents", response_model=DocumentOut)
async def upload_document(
    file: UploadFile, ctx: RequestContext = Depends(get_request_context)
) -> DocumentOut:
    authorize_use_knowledge(ctx.workspace)
    settings = get_settings()
    data = await file.read()
    document = await ingest_file(
        ctx.db,
        get_object_storage(settings),
        customer_id=ctx.workspace.customer_id,
        workspace_id=ctx.workspace.workspace_id,
        uploader_id=f"user:{ctx.workspace.user_id}",
        filename=file.filename or "",
        declared_content_type=file.content_type or "",
        data=data,
        max_size_bytes=settings.knowledge_max_file_size_bytes,
    )
    return _to_document_out(document)


@router.get("/v1/workspaces/{workspace_id}/documents", response_model=list[DocumentOut])
async def list_workspace_documents(
    limit: int = Query(default=50, le=200), ctx: RequestContext = Depends(get_request_context)
) -> list[DocumentOut]:
    documents = await list_documents_for_workspace(
        ctx.db, workspace_id=ctx.workspace.workspace_id, limit=limit
    )
    return [_to_document_out(document) for document in documents]


@router.get("/v1/workspaces/{workspace_id}/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> DocumentOut:
    document = await _get_owned_document(ctx, document_id)
    return _to_document_out(document)


@router.get("/v1/workspaces/{workspace_id}/documents/{document_id}/content")
async def download_document(
    document_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> Response:
    document = await _get_owned_document(ctx, document_id)
    storage = get_object_storage(get_settings())
    try:
        data = await storage.get(document.storage_key)
    except ObjectNotFoundError:
        # The DB row survived but the object did not (e.g. a crash
        # between delete_document's two steps, or manual storage
        # tampering) — a distinct, honest 404 rather than a 500, but
        # deliberately not the ingest_file/delete_document error type
        # (there is no caller input to validate here).
        raise HTTPException(status_code=404, detail="document content not found") from None
    return Response(content=data, media_type=document.content_type)


@router.delete("/v1/workspaces/{workspace_id}/documents/{document_id}", status_code=204)
async def delete_workspace_document(
    document_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> None:
    authorize_use_knowledge(ctx.workspace)
    document = await _get_owned_document(ctx, document_id)
    await delete_document(ctx.db, get_object_storage(get_settings()), document)
