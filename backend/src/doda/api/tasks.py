"""Task endpoints — FR-TASK. Same authoritative-chain pattern as
api/actions.py: every handler gets its tenant/authz context only from
RequestContext, never from client-supplied customer_id/actor_id."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from doda.api.dependencies import RequestContext, get_request_context
from doda.api.task_schemas import (
    ChangeTaskStatusRequest,
    CreateTaskRequest,
    TaskHistoryEntryOut,
    TaskOut,
)
from doda.application.authz_service import authorize_create_task, authorize_task_mutation
from doda.application.task_service import (
    change_task_status,
    create_task,
    list_task_history,
    list_tasks_for_workspace,
)
from doda.domain.task.models import Task, TaskStatus

router = APIRouter(tags=["tasks"])


def _to_task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        workspace_id=task.workspace_id,
        owner_id=task.owner_id,
        title=task.title,
        status=task.status,
        due_date=task.due_date,
        parent_task_id=task.parent_task_id,
    )


@router.post("/v1/workspaces/{workspace_id}/tasks", response_model=TaskOut)
async def create_workspace_task(
    body: CreateTaskRequest, ctx: RequestContext = Depends(get_request_context)
) -> TaskOut:
    authorize_create_task(ctx.workspace)
    task = await create_task(
        ctx.db,
        customer_id=ctx.workspace.customer_id,
        workspace_id=ctx.workspace.workspace_id,
        owner_id=f"user:{ctx.workspace.user_id}",
        title=body.title,
        due_date=body.due_date,
        parent_task_id=body.parent_task_id,
    )
    return _to_task_out(task)


@router.get("/v1/workspaces/{workspace_id}/tasks", response_model=list[TaskOut])
async def list_workspace_tasks(
    status: TaskStatus | None = None,
    limit: int = Query(default=50, le=200),
    ctx: RequestContext = Depends(get_request_context),
) -> list[TaskOut]:
    tasks = await list_tasks_for_workspace(
        ctx.db, workspace_id=ctx.workspace.workspace_id, status=status, limit=limit
    )
    return [_to_task_out(task) for task in tasks]


async def _get_owned_task(ctx: RequestContext, task_id: uuid.UUID) -> Task:
    task = await ctx.db.get(Task, task_id)
    if task is None or task.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/v1/workspaces/{workspace_id}/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)) -> TaskOut:
    task = await _get_owned_task(ctx, task_id)
    return _to_task_out(task)


@router.post("/v1/workspaces/{workspace_id}/tasks/{task_id}/status", response_model=TaskOut)
async def change_workspace_task_status(
    task_id: uuid.UUID,
    body: ChangeTaskStatusRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> TaskOut:
    task = await _get_owned_task(ctx, task_id)
    authorize_task_mutation(ctx.workspace, task)
    task = await change_task_status(
        ctx.db, task, target=body.target_status, actor_id=f"user:{ctx.workspace.user_id}"
    )
    return _to_task_out(task)


@router.get(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/history",
    response_model=list[TaskHistoryEntryOut],
)
async def get_task_history(
    task_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> list[TaskHistoryEntryOut]:
    await _get_owned_task(ctx, task_id)  # 404s before revealing any history exists
    history = await list_task_history(ctx.db, task_id)
    return [
        TaskHistoryEntryOut(
            id=entry.id,
            actor_id=entry.actor_id,
            from_status=entry.from_status,
            to_status=entry.to_status,
            created_at=entry.created_at,
        )
        for entry in history
    ]
