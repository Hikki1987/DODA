"""The AI tool registry — the one place `doda.application.
conversation_service` looks up what a model is allowed to call, and how.
Two categories, matching TRD 9.1/9.2 exactly (8-band instruction: "Vosita
chaqiruvi — ruxsat berilgan harakat degani emas. Har bir chaqiruvda
argumentlar, foydalanuvchi vakolati va amalning xavfi tekshirilsin"):

- READ tools execute immediately and return their result to the model —
  no external side effect, no Action/Approval row, because the
  workspace-membership check already performed before a conversation
  exists (`authorize_use_chat`) is exactly the authority a plain read
  needs. Today: `list_my_open_tasks`.
- WRITE tools never execute here at all. They call `doda.application.
  action_service.propose_action`/`submit_action_for_execution` — the
  SAME risk-based approval chain every other Action goes through
  (9.1/9.2, FR-ACT-004 idempotency). A model "calling" a write tool can
  only ever produce a DRAFT/AWAITING_APPROVAL Action; nothing it does
  executes without a human approval, same as any other R3+ action.
  Today: `telegram_send_message` (-> tool_name `telegram.send_message`,
  already R3-floored by `domain.action.tool_policy`).

Every tool's arguments are validated against a Pydantic model BEFORE
dispatch — the model's raw JSON is never trusted as a safe call (Master
Instruction: "Model chiqishini ishonchli deb qabul qilma"). Invalid
arguments raise `ToolArgumentsInvalidError`, which
`doda.application.conversation_service` turns into a tool-result error
message fed back to the model, never a crash.

A deterministic idempotency key (`conversation_id:assistant_message_id:
call_id`) is used for every WRITE tool's Action — not a fresh
`uuid.uuid4()` — so a retried gateway call that re-surfaces "the same"
tool call (the adapter's own retry, or a user-visible retry button)
collapses onto the existing Action via the UNIQUE constraint already
enforced by `propose_action`, rather than creating a second one (the
6/10-band instruction: "Retry sababli... amal takrorlanishining oldini
ol").
"""

import json
import uuid
from typing import Any

import pydantic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.ai.types import ToolSpec
from doda.application.action_service import propose_action, submit_action_for_execution
from doda.application.authz_service import WorkspaceContext
from doda.application.task_service import list_tasks_for_workspace
from doda.domain.action.approval import Approval
from doda.domain.action.models import Action, ActionStatus, RiskLevel
from doda.domain.task.models import TaskStatus


class ToolArgumentsInvalidError(Exception):
    def __init__(self, tool_name: str, reason: str) -> None:
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"{tool_name}: {reason}")


class ToolNotFoundError(Exception):
    pass


class ListMyOpenTasksArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    limit: int = pydantic.Field(default=20, ge=1, le=50)


class TelegramSendMessageArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    chat_id: str
    text: str = pydantic.Field(max_length=4096)


_READ_TOOL_ARGS: dict[str, type[pydantic.BaseModel]] = {
    "list_my_open_tasks": ListMyOpenTasksArgs,
}
_WRITE_TOOL_ARGS: dict[str, type[pydantic.BaseModel]] = {
    "telegram_send_message": TelegramSendMessageArgs,
}
# The tool_name Action/tool_policy.py actually knows about — deliberately
# not the same string the model sees (`telegram_send_message`, a valid
# Python-identifier-shaped function name every provider's tool-calling
# API requires) vs the dotted `tool_name` this codebase's Action/
# tool_policy layer already uses elsewhere (`telegram.send_message`).
_WRITE_TOOL_ACTION_NAME: dict[str, str] = {
    "telegram_send_message": "telegram.send_message",
}


def available_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="list_my_open_tasks",
            description="List the caller's own open (TODO/IN_PROGRESS) tasks in this workspace.",
            parameters_schema=ListMyOpenTasksArgs.model_json_schema(),
        ),
        ToolSpec(
            name="telegram_send_message",
            description=(
                "Propose sending a Telegram message. This never sends immediately — it creates an "
                "action that requires human approval before anything is sent."
            ),
            parameters_schema=TelegramSendMessageArgs.model_json_schema(),
        ),
    ]


def _validate_arguments(
    tool_name: str, arguments_json: str, schema: dict[str, type[pydantic.BaseModel]]
) -> Any:
    model_cls = schema.get(tool_name)
    if model_cls is None:
        raise ToolNotFoundError(tool_name)
    try:
        return model_cls.model_validate_json(arguments_json)
    except pydantic.ValidationError as exc:
        raise ToolArgumentsInvalidError(tool_name, str(exc.errors(include_url=False))) from None


async def dispatch_read_tool(
    session: AsyncSession, *, tool_name: str, arguments_json: str, workspace_id: uuid.UUID
) -> str:
    """Executes immediately; returns the tool's result as a string to
    feed back to the model as a TOOL-role turn. Raises
    ToolArgumentsInvalidError/ToolNotFoundError — never a bare exception
    from the underlying service — so the caller can always turn a
    failure into a tool-result error message instead of crashing the
    whole turn."""
    args = _validate_arguments(tool_name, arguments_json, _READ_TOOL_ARGS)

    if tool_name == "list_my_open_tasks":
        assert isinstance(args, ListMyOpenTasksArgs)
        todo = await list_tasks_for_workspace(
            session, workspace_id=workspace_id, status=TaskStatus.TODO, limit=args.limit
        )
        in_progress = await list_tasks_for_workspace(
            session, workspace_id=workspace_id, status=TaskStatus.IN_PROGRESS, limit=args.limit
        )
        tasks = (todo + in_progress)[: args.limit]
        if not tasks:
            return "No open tasks."
        return "\n".join(f"- [{t.status.value}] {t.title} (id={t.id})" for t in tasks)

    raise ToolNotFoundError(tool_name)


def is_read_tool(tool_name: str) -> bool:
    return tool_name in _READ_TOOL_ARGS


def is_write_tool(tool_name: str) -> bool:
    return tool_name in _WRITE_TOOL_ARGS


async def propose_write_tool_action(
    session: AsyncSession,
    *,
    tool_name: str,
    arguments_json: str,
    workspace_context: WorkspaceContext,
    trace_id: uuid.UUID,
    idempotency_key: str,
) -> tuple[Action, Approval | None]:
    """Validates arguments, then routes through the EXACT SAME
    propose/validate/approval chain every other Action uses — this
    function does not decide risk level, approval requirement, or
    idempotency itself; `action_service`/`tool_policy` already do, and
    re-deciding any of that here would be the kind of authorization
    logic the AI/tool-registry layer must never own (6.2: "AI qatlami
    authoritative avtorizatsiya qarorini chiqarmaydi")."""
    _validate_arguments(tool_name, arguments_json, _WRITE_TOOL_ARGS)
    action_tool_name = _WRITE_TOOL_ACTION_NAME[tool_name]
    actor_id = f"user:{workspace_context.user_id}"

    action, created = await propose_action(
        session,
        customer_id=workspace_context.customer_id,
        workspace_id=workspace_context.workspace_id,
        trace_id=trace_id,
        actor_id=actor_id,
        tool_name=action_tool_name,
        risk_level=RiskLevel.R3,
        payload=json.loads(arguments_json),
        idempotency_key=idempotency_key,
    )
    if created:
        return await submit_action_for_execution(session, action, actor_id=actor_id)

    # Idempotent replay (FR-ACT-004) — same handling as api/actions.py's
    # propose_and_submit_action: the action already went through its
    # lifecycle on the call this one is retrying, so re-running
    # validate_action here would attempt an illegal state transition
    # (e.g. AWAITING_APPROVAL -> VALIDATING). Hand back its current state
    # instead of re-processing it.
    approval: Approval | None = None
    if action.status is ActionStatus.AWAITING_APPROVAL:
        approval = await session.scalar(
            select(Approval)
            .where(Approval.action_id == action.id)
            .order_by(Approval.created_at.desc())
            .limit(1)
        )
    return action, approval
