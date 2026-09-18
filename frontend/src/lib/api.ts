// Thin, typed client for the DODA backend (see backend/src/doda/api/*.py).
// No codegen — the backend has no OpenAPI schema export wired up yet, so
// these types are hand-kept in sync with the Pydantic response models.
// Every function takes sessionId explicitly (never reads it from storage
// itself) so server components / tests can call the same functions.

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public traceId: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function authHeaders(sessionId: string): Record<string, string> {
  return { Authorization: `Bearer ${sessionId}` };
}

// Every endpoint (plain JSON or streamConversationMessage's SSE POST) fails
// with the same envelope shape — shared so a non-2xx response is always
// turned into the same ApiError, whether or not the caller ever reads a body.
async function throwApiError(response: Response): Promise<never> {
  const body = await response.json().catch(() => ({}));
  throw new ApiError(
    response.status,
    body.code ?? "UNKNOWN",
    body.message ?? "Noma'lum xato yuz berdi",
    body.trace_id ?? "",
  );
}

async function apiFetch<T>(
  path: string,
  sessionId: string,
  init?: RequestInit & { idempotencyKey?: string },
): Promise<T> {
  const headers: Record<string, string> = {
    ...authHeaders(sessionId),
    ...(init?.body ? { "Content-Type": "application/json" } : {}),
    ...(init?.idempotencyKey ? { "Idempotency-Key": init.idempotencyKey } : {}),
  };

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (response.status === 204) {
    return undefined as T;
  }

  if (!response.ok) {
    await throwApiError(response);
  }

  return (await response.json()) as T;
}

// ---- /v1/sessions — used only to validate a pasted dev session id ----

export interface SessionOut {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  auth_strength: "AAL1" | "AAL2";
  is_current: boolean;
}

export function listMySessions(sessionId: string): Promise<SessionOut[]> {
  return apiFetch("/v1/sessions", sessionId);
}

export function revokeSession(sessionId: string, targetSessionId: string): Promise<void> {
  return apiFetch(`/v1/sessions/${targetSessionId}`, sessionId, { method: "DELETE" });
}

// ---- /v1/me/workspaces ----

export interface MyWorkspaceOut {
  customer_id: string;
  customer_name: string;
  workspace_id: string;
  workspace_name: string;
  role: string;
}

export function listMyWorkspaces(sessionId: string): Promise<MyWorkspaceOut[]> {
  return apiFetch("/v1/me/workspaces", sessionId);
}

// ---- /v1/me/customers ----

export interface MyCustomerOut {
  customer_id: string;
  customer_name: string;
  role: string;
}

export function listMyCustomers(sessionId: string): Promise<MyCustomerOut[]> {
  return apiFetch("/v1/me/customers", sessionId);
}

// ---- /v1/me/export ----

export interface MyDataExportOut {
  user_id: string;
  display_name: string;
  memberships: MyWorkspaceOut[];
  tasks: TaskOut[];
  notifications: NotificationOut[];
  audit_events: AuditEventOut[];
}

export function getMyDataExport(sessionId: string): Promise<MyDataExportOut> {
  return apiFetch("/v1/me/export", sessionId);
}

// ---- /v1/workspaces/{id}/tasks ----

export type TaskStatus = "TODO" | "IN_PROGRESS" | "DONE" | "CANCELLED";

export interface TaskOut {
  id: string;
  workspace_id: string;
  owner_id: string;
  title: string;
  status: TaskStatus;
  due_date: string | null;
  parent_task_id: string | null;
}

export function listTasks(sessionId: string, workspaceId: string): Promise<TaskOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks`, sessionId);
}

export function createTask(
  sessionId: string,
  workspaceId: string,
  title: string,
  dueDate?: string | null,
): Promise<TaskOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks`, sessionId, {
    method: "POST",
    body: JSON.stringify({ title, due_date: dueDate ?? null }),
  });
}

// FR-TASK-002: a deterministic deadline filter, not an AI-generated
// plan — see the backend's own docstring (doda.application.task_service.
// generate_task_plan) for why "plan" here means exactly that.
export type TaskPlanPeriod = "daily" | "weekly";

export function getTaskPlan(
  sessionId: string,
  workspaceId: string,
  period: TaskPlanPeriod,
): Promise<TaskOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/plan?period=${period}`, sessionId);
}

export function changeTaskStatus(
  sessionId: string,
  workspaceId: string,
  taskId: string,
  targetStatus: TaskStatus,
): Promise<TaskOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/${taskId}/status`, sessionId, {
    method: "POST",
    body: JSON.stringify({ target_status: targetStatus }),
  });
}

export interface TaskHistoryEntryOut {
  id: string;
  actor_id: string;
  from_status: TaskStatus | null;
  to_status: TaskStatus;
  created_at: string;
}

export function getTaskHistory(
  sessionId: string,
  workspaceId: string,
  taskId: string,
): Promise<TaskHistoryEntryOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/${taskId}/history`, sessionId);
}

// FR-TASK-003: a decision record (variant considered, tradeoff, decision,
// reason). Recording a new one never edits an earlier row — the list is
// every version ever recorded, oldest first, never just "the current one".
export interface TaskDecisionOut {
  id: string;
  actor_id: string;
  variant: string;
  tradeoff: string;
  decision: string;
  reason: string;
  created_at: string;
}

export function getTaskDecisions(
  sessionId: string,
  workspaceId: string,
  taskId: string,
): Promise<TaskDecisionOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/${taskId}/decisions`, sessionId);
}

export function recordTaskDecision(
  sessionId: string,
  workspaceId: string,
  taskId: string,
  fields: { variant: string; tradeoff: string; decision: string; reason: string },
): Promise<TaskDecisionOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/${taskId}/decisions`, sessionId, {
    method: "POST",
    body: JSON.stringify(fields),
  });
}

// FR-TASK-005: a reminder REQUEST never fires on its own — it stays
// PENDING_CONFIRMATION until confirmReminder is called with the exact
// same remind_at it was created with (the time itself is what's being
// confirmed, not just an id).
export type ReminderStatus = "PENDING_CONFIRMATION" | "CONFIRMED" | "CANCELLED" | "FIRED";

export interface ReminderOut {
  id: string;
  task_id: string;
  actor_id: string;
  remind_at: string;
  status: ReminderStatus;
  confirmed_at: string | null;
  fired_at: string | null;
  created_at: string;
}

export function getTaskReminders(
  sessionId: string,
  workspaceId: string,
  taskId: string,
): Promise<ReminderOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/${taskId}/reminders`, sessionId);
}

export function requestTaskReminder(
  sessionId: string,
  workspaceId: string,
  taskId: string,
  remindAt: string,
): Promise<ReminderOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/${taskId}/reminders`, sessionId, {
    method: "POST",
    body: JSON.stringify({ remind_at: remindAt }),
  });
}

export function confirmTaskReminder(
  sessionId: string,
  workspaceId: string,
  taskId: string,
  reminderId: string,
  remindAt: string,
): Promise<ReminderOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/${taskId}/reminders/${reminderId}/confirm`, sessionId, {
    method: "POST",
    body: JSON.stringify({ remind_at: remindAt }),
  });
}

export function cancelTaskReminder(
  sessionId: string,
  workspaceId: string,
  taskId: string,
  reminderId: string,
): Promise<ReminderOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks/${taskId}/reminders/${reminderId}/cancel`, sessionId, {
    method: "POST",
  });
}

// ---- /v1/workspaces/{id}/actions ----

export type ActionStatus =
  | "DRAFT"
  | "VALIDATING"
  | "AWAITING_APPROVAL"
  | "READY"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "RETRYING"
  | "COMPENSATING"
  | "COMPENSATED"
  | "DENIED"
  | "REJECTED"
  | "EXPIRED"
  | "CANCELLED";

export interface ActionOut {
  id: string;
  workspace_id: string;
  trace_id: string;
  tool_name: string;
  risk_level: string;
  status: ActionStatus;
  payload: Record<string, unknown>;
  preview: string;
}

export function listActions(sessionId: string, workspaceId: string): Promise<ActionOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/actions`, sessionId);
}

// FR-ACT-009: cancels a READY action outright, or (for one already
// RUNNING) requests its reversal — the backend resolves which, the
// caller doesn't need to. Completing a compensation (COMPENSATING ->
// COMPENSATED/FAILED) is WorkspaceAdmin-only and human-attested — not
// exposed here yet, since a RUNNING action is rare enough (only a relay
// worker reaches it) that a dedicated admin form would be premature UI
// for an edge case; the backend endpoint exists and is tested.
export function cancelAction(sessionId: string, workspaceId: string, actionId: string): Promise<ActionOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/actions/${actionId}/cancel`, sessionId, {
    method: "POST",
  });
}

// ---- /v1/workspaces/{id}/notifications ----

export interface NotificationOut {
  id: string;
  workspace_id: string | null;
  notification_type: "PENDING_APPROVAL" | "FAILED_ACTION" | "COMPLETED_TASK" | "SECURITY_ALERT";
  reference_type: string;
  reference_id: string;
  safe_metadata: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
}

export function listNotifications(sessionId: string, workspaceId: string): Promise<NotificationOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/notifications`, sessionId);
}

export function markNotificationRead(
  sessionId: string,
  workspaceId: string,
  notificationId: string,
): Promise<NotificationOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/notifications/${notificationId}/read`, sessionId, {
    method: "POST",
  });
}

// ---- /v1/workspaces/{id}/kill-switch ----

export interface KillSwitchStatusOut {
  engaged: boolean;
  reason: string | null;
  engaged_at: string | null;
  engaged_by: string | null;
}

export function getWorkspaceKillSwitch(sessionId: string, workspaceId: string): Promise<KillSwitchStatusOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/kill-switch`, sessionId);
}

export function engageWorkspaceKillSwitch(
  sessionId: string,
  workspaceId: string,
  reason: string,
): Promise<KillSwitchStatusOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/kill-switch/engage`, sessionId, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function disengageWorkspaceKillSwitch(
  sessionId: string,
  workspaceId: string,
): Promise<KillSwitchStatusOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/kill-switch/disengage`, sessionId, { method: "POST" });
}

// ---- /v1/workspaces/{id}/members ----

export interface WorkspaceMemberOut {
  membership_id: string | null;
  user_id: string;
  display_name: string;
  role: string;
}

export function listWorkspaceMembers(sessionId: string, workspaceId: string): Promise<WorkspaceMemberOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/members`, sessionId);
}

export type WorkspaceRole = "workspace_admin" | "member";

export function changeWorkspaceMemberRole(
  sessionId: string,
  workspaceId: string,
  membershipId: string,
  role: WorkspaceRole,
): Promise<unknown> {
  return apiFetch(`/v1/workspaces/${workspaceId}/members/${membershipId}`, sessionId, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeWorkspaceMember(
  sessionId: string,
  workspaceId: string,
  membershipId: string,
): Promise<void> {
  return apiFetch(`/v1/workspaces/${workspaceId}/members/${membershipId}`, sessionId, {
    method: "DELETE",
  });
}

// ---- /v1/workspaces/{id}/audit ----

export interface AuditEventOut {
  id: string;
  customer_id: string;
  workspace_id: string | null;
  trace_id: string;
  actor_id: string;
  event_type: string;
  occurred_at: string;
  safe_metadata: Record<string, unknown>;
  prev_hash: string | null;
  hash: string;
}

export function listWorkspaceAudit(
  sessionId: string,
  workspaceId: string,
  traceId?: string,
): Promise<AuditEventOut[]> {
  const query = traceId ? `?trace_id=${encodeURIComponent(traceId)}` : "";
  return apiFetch(`/v1/workspaces/${workspaceId}/audit${query}`, sessionId);
}

// ---- /v1/customers/{id}/audit ----

export function listCustomerAudit(
  sessionId: string,
  customerId: string,
  traceId?: string,
): Promise<AuditEventOut[]> {
  const query = traceId ? `?trace_id=${encodeURIComponent(traceId)}` : "";
  return apiFetch(`/v1/customers/${customerId}/audit${query}`, sessionId);
}

export interface AuditChainViolationOut {
  event_id: string;
  reason: string;
}

export interface AuditChainVerificationOut {
  ok: boolean;
  checked_count: number;
  violations: AuditChainViolationOut[];
}

export function verifyCustomerAuditChain(
  sessionId: string,
  customerId: string,
): Promise<AuditChainVerificationOut> {
  return apiFetch(`/v1/customers/${customerId}/audit/verify`, sessionId);
}

// FR-AUD-005: bundles one trace_id's full event set with a per-event hash
// recomputation AND the whole-customer chain-verification result — see
// the backend's own EvidencePackage docstring for why those are two
// distinct claims, not one.
export interface EvidenceEventOut {
  id: string;
  event_type: string;
  actor_id: string;
  workspace_id: string | null;
  occurred_at: string;
  safe_metadata: Record<string, unknown>;
  prev_hash: string | null;
  hash: string;
  hash_self_consistent: boolean;
}

export interface EvidencePackageOut {
  customer_id: string;
  trace_id: string;
  events: EvidenceEventOut[];
  full_chain_verification: AuditChainVerificationOut;
}

export function getCustomerAuditEvidencePackage(
  sessionId: string,
  customerId: string,
  traceId: string,
): Promise<EvidencePackageOut> {
  return apiFetch(
    `/v1/customers/${customerId}/audit/evidence-package?trace_id=${encodeURIComponent(traceId)}`,
    sessionId,
  );
}

// ---- /v1/customers/{id}/kill-switch ----

export function getCustomerKillSwitch(sessionId: string, customerId: string): Promise<KillSwitchStatusOut> {
  return apiFetch(`/v1/customers/${customerId}/kill-switch`, sessionId);
}

export function engageCustomerKillSwitch(
  sessionId: string,
  customerId: string,
  reason: string,
): Promise<KillSwitchStatusOut> {
  return apiFetch(`/v1/customers/${customerId}/kill-switch/engage`, sessionId, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function disengageCustomerKillSwitch(
  sessionId: string,
  customerId: string,
): Promise<KillSwitchStatusOut> {
  return apiFetch(`/v1/customers/${customerId}/kill-switch/disengage`, sessionId, { method: "POST" });
}

// ---- /v1/customers/{id}/members ----

export type CustomerRole = "customer_owner" | "member" | "auditor";

export interface CustomerMemberOut {
  membership_id: string;
  user_id: string;
  display_name: string;
  role: string;
}

export function listCustomerMembers(sessionId: string, customerId: string): Promise<CustomerMemberOut[]> {
  return apiFetch(`/v1/customers/${customerId}/members`, sessionId);
}

export function inviteCustomerMember(
  sessionId: string,
  customerId: string,
  userId: string,
  role: CustomerRole,
): Promise<unknown> {
  return apiFetch(`/v1/customers/${customerId}/members`, sessionId, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, role }),
  });
}

export function changeCustomerMemberRole(
  sessionId: string,
  customerId: string,
  membershipId: string,
  role: CustomerRole,
): Promise<unknown> {
  return apiFetch(`/v1/customers/${customerId}/members/${membershipId}`, sessionId, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeCustomerMember(
  sessionId: string,
  customerId: string,
  membershipId: string,
): Promise<void> {
  return apiFetch(`/v1/customers/${customerId}/members/${membershipId}`, sessionId, {
    method: "DELETE",
  });
}

// ---- /v1/customers/{id}/notifications ----

export function listCustomerNotifications(
  sessionId: string,
  customerId: string,
): Promise<NotificationOut[]> {
  return apiFetch(`/v1/customers/${customerId}/notifications`, sessionId);
}

export function markCustomerNotificationRead(
  sessionId: string,
  customerId: string,
  notificationId: string,
): Promise<NotificationOut> {
  return apiFetch(`/v1/customers/${customerId}/notifications/${notificationId}/read`, sessionId, {
    method: "POST",
  });
}

// ---- /v1/customers/{id}/workspaces/archived, /v1/workspaces/{id}/restore ----

export interface WorkspaceOut {
  id: string;
  customer_id: string;
  name: string;
  archived_at: string | null;
}

export function listArchivedWorkspaces(sessionId: string, customerId: string): Promise<WorkspaceOut[]> {
  return apiFetch(`/v1/customers/${customerId}/workspaces/archived`, sessionId);
}

export function archiveWorkspace(sessionId: string, workspaceId: string): Promise<WorkspaceOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/archive`, sessionId, { method: "POST" });
}

export function restoreWorkspace(sessionId: string, workspaceId: string): Promise<WorkspaceOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/restore`, sessionId, { method: "POST" });
}

// ---- /v1/customers/{id}/notification-preferences ----

export type NotificationType = "PENDING_APPROVAL" | "FAILED_ACTION" | "COMPLETED_TASK" | "SECURITY_ALERT";

export interface NotificationPreferenceOut {
  notification_type: NotificationType;
  enabled: boolean;
}

export function listNotificationPreferences(
  sessionId: string,
  customerId: string,
): Promise<NotificationPreferenceOut[]> {
  return apiFetch(`/v1/customers/${customerId}/notification-preferences`, sessionId);
}

export function setNotificationPreference(
  sessionId: string,
  customerId: string,
  notificationType: NotificationType,
  enabled: boolean,
): Promise<NotificationPreferenceOut> {
  return apiFetch(`/v1/customers/${customerId}/notification-preferences/${notificationType}`, sessionId, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

// ---- AI: /v1/workspaces/{id}/conversations — FR-CONV ----

export type AiProvider = "OPENAI" | "GEMINI" | "CLAUDE";
export const AI_PROVIDERS: AiProvider[] = ["OPENAI", "GEMINI", "CLAUDE"];
export type ChatMode = "FAST" | "STANDARD" | "DEEP";
export type MessageRole = "USER" | "ASSISTANT" | "TOOL";
// FR-CONV-001. Mirrors doda.ai.language.SUPPORTED_LANGUAGES.
export type AiLanguage = "UZ" | "RU" | "EN";
export const AI_LANGUAGES: AiLanguage[] = ["UZ", "RU", "EN"];

export interface ConversationOut {
  id: string;
  workspace_id: string;
  owner_id: string;
  title: string | null;
  pinned_provider: AiProvider | null;
  pinned_model: string | null;
  pinned_language: AiLanguage | null;
  created_at: string;
}

export interface MessageOut {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  tool_call_id: string | null;
  tool_name: string | null;
  provider: AiProvider | null;
  model: string | null;
  finish_reason: string | null;
  created_at: string;
}

export function createConversation(
  sessionId: string,
  workspaceId: string,
  title?: string,
): Promise<ConversationOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/conversations`, sessionId, {
    method: "POST",
    body: JSON.stringify({ title: title ?? null }),
  });
}

export function listConversations(sessionId: string, workspaceId: string): Promise<ConversationOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/conversations`, sessionId);
}

export function listConversationMessages(
  sessionId: string,
  workspaceId: string,
  conversationId: string,
): Promise<MessageOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`, sessionId);
}

// FR-CONV-006: searches message content across every conversation in this
// workspace (not just one) — a blank query intentionally returns nothing
// rather than the whole history, see the backend's own docstring.
export function searchConversations(
  sessionId: string,
  workspaceId: string,
  query: string,
): Promise<MessageOut[]> {
  return apiFetch(
    `/v1/workspaces/${workspaceId}/conversations/search?q=${encodeURIComponent(query)}`,
    sessionId,
  );
}

export function switchConversationProvider(
  sessionId: string,
  workspaceId: string,
  conversationId: string,
  provider: AiProvider,
  model?: string | null,
): Promise<ConversationOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/conversations/${conversationId}/provider`, sessionId, {
    method: "POST",
    body: JSON.stringify({ provider, model: model ?? null }),
  });
}

// FR-CONV-001. `language: null` clears the pin, reverting to per-message
// auto-detection (doda.ai.language.detect_language) on the backend.
export function switchConversationLanguage(
  sessionId: string,
  workspaceId: string,
  conversationId: string,
  language: AiLanguage | null,
): Promise<ConversationOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/conversations/${conversationId}/language`, sessionId, {
    method: "POST",
    body: JSON.stringify({ language }),
  });
}

// The one endpoint that isn't plain request/response JSON: the backend
// replies over SSE (`text/event-stream`) because a turn can take several
// tool-call rounds (see backend/src/doda/api/conversations.py's own
// docstring). `fetch()` + a manual ReadableStream reader is the only way
// to consume a streaming POST body from the browser — EventSource only
// supports GET. Event names match the backend's `_sse_frame`/TurnChunk
// kinds exactly: "text"/"tool_status" carry `{text}`, "done" carries
// `{message}` (the persisted final assistant Message, or null if the
// turn ended without producing one — e.g. a write-tool call), "error" is
// the mid-stream failure frame (`api/conversations.py`'s `_error_frame`).
export type ConversationStreamEvent =
  | { kind: "text" | "tool_status"; text: string }
  | { kind: "done"; message: MessageOut | null }
  | { kind: "error"; code: string; message: string; trace_id: string; retryable: boolean };

export async function* streamConversationMessage(
  sessionId: string,
  workspaceId: string,
  conversationId: string,
  content: string,
  mode: ChatMode = "STANDARD",
  signal?: AbortSignal,
): AsyncGenerator<ConversationStreamEvent> {
  // FR-CONV-002: aborting this fetch (the caller's Cancel button) is
  // what the backend's `Request.is_disconnected()` check
  // (`api/conversations.py`) actually detects — there is no separate
  // cancel endpoint; the HTTP connection itself is the cancellation
  // signal, same as any other streaming-fetch cancellation.
  const response = await fetch(
    `${API_BASE_URL}/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`,
    {
      method: "POST",
      headers: { ...authHeaders(sessionId), "Content-Type": "application/json" },
      body: JSON.stringify({ content, mode }),
      signal,
    },
  );

  if (!response.ok) {
    // Pre-stream failure (budget/capability/provider error on round 0) —
    // a normal JSON error body, same shape as every other endpoint.
    await throwApiError(response);
  }
  if (response.body === null) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let frameEnd = buffer.indexOf("\n\n");
    while (frameEnd !== -1) {
      const frame = buffer.slice(0, frameEnd);
      buffer = buffer.slice(frameEnd + 2);
      const eventLine = frame.split("\n").find((line) => line.startsWith("event: "));
      const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
      if (eventLine && dataLine) {
        const kind = eventLine.slice("event: ".length);
        const data = JSON.parse(dataLine.slice("data: ".length));
        yield { kind, ...data } as ConversationStreamEvent;
      }
      frameEnd = buffer.indexOf("\n\n");
    }
  }
}

// ---- AI: /v1/customers/{id}/ai-providers, /ai-fallback — ADR-009's settings gap ----

export interface ProviderStatusOut {
  provider: AiProvider;
  configured: boolean;
  enabled: boolean;
  verified_at: string | null;
  verified_ok: boolean | null;
  verified_error: string | null;
}

export function listProviderStatuses(sessionId: string, customerId: string): Promise<ProviderStatusOut[]> {
  return apiFetch(`/v1/customers/${customerId}/ai-providers`, sessionId);
}

export function setProviderEnabled(
  sessionId: string,
  customerId: string,
  provider: AiProvider,
  enabled: boolean,
): Promise<ProviderStatusOut> {
  return apiFetch(`/v1/customers/${customerId}/ai-providers/${provider}/enabled`, sessionId, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

export interface TestProviderConnectionOut {
  provider: AiProvider;
  ok: boolean;
  error: string | null;
}

export function testProviderConnection(
  sessionId: string,
  customerId: string,
  provider: AiProvider,
): Promise<TestProviderConnectionOut> {
  return apiFetch(`/v1/customers/${customerId}/ai-providers/${provider}/test-connection`, sessionId, {
    method: "POST",
  });
}

export interface AiFallbackSettingOut {
  enabled: boolean;
}

export function getAiFallbackSetting(sessionId: string, customerId: string): Promise<AiFallbackSettingOut> {
  return apiFetch(`/v1/customers/${customerId}/ai-fallback`, sessionId);
}

export function setAiFallbackSetting(
  sessionId: string,
  customerId: string,
  enabled: boolean,
): Promise<AiFallbackSettingOut> {
  return apiFetch(`/v1/customers/${customerId}/ai-fallback`, sessionId, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

// ---- AI preference — 4-tier: conversation pin > user > workspace > system default ----

export interface AiPreferenceOut {
  provider: AiProvider | null;
  model: string | null;
}

export function getMyAiPreference(sessionId: string, customerId: string): Promise<AiPreferenceOut> {
  return apiFetch(`/v1/customers/${customerId}/me/ai-preference`, sessionId);
}

export function setMyAiPreference(
  sessionId: string,
  customerId: string,
  provider: AiProvider,
  model?: string | null,
): Promise<AiPreferenceOut> {
  return apiFetch(`/v1/customers/${customerId}/me/ai-preference`, sessionId, {
    method: "PUT",
    body: JSON.stringify({ provider, model: model ?? null }),
  });
}

export function clearMyAiPreference(sessionId: string, customerId: string): Promise<void> {
  return apiFetch(`/v1/customers/${customerId}/me/ai-preference`, sessionId, { method: "DELETE" });
}

export function getWorkspaceAiPreference(sessionId: string, workspaceId: string): Promise<AiPreferenceOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/ai-preference`, sessionId);
}

export function setWorkspaceAiPreference(
  sessionId: string,
  workspaceId: string,
  provider: AiProvider,
  model?: string | null,
): Promise<AiPreferenceOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/ai-preference`, sessionId, {
    method: "PUT",
    body: JSON.stringify({ provider, model: model ?? null }),
  });
}

export function clearWorkspaceAiPreference(sessionId: string, workspaceId: string): Promise<void> {
  return apiFetch(`/v1/workspaces/${workspaceId}/ai-preference`, sessionId, { method: "DELETE" });
}

// FR-WKS-007's "til" facet: a workspace-level default language, versioned
// and audited server-side. Distinct from AiPreference above — this has no
// "clear" (null just means "no override", the same shape PUT already
// accepts), and no conversation-level tier reads it directly; it only
// ever feeds conversation_service's language-resolution fallback.
export interface WorkspaceLanguageSettingOut {
  language: AiLanguage | null;
}

export function getWorkspaceLanguageSetting(
  sessionId: string,
  workspaceId: string,
): Promise<WorkspaceLanguageSettingOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/language-setting`, sessionId);
}

export function setWorkspaceLanguageSetting(
  sessionId: string,
  workspaceId: string,
  language: AiLanguage | null,
): Promise<WorkspaceLanguageSettingOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/language-setting`, sessionId, {
    method: "PUT",
    body: JSON.stringify({ language }),
  });
}

// ---- AI budget — NFR-COST-001's "byudjet va alert" ----

export interface AiBudgetStatusOut {
  year_month: string;
  soft_cap_usd: number;
  hard_cap_usd: number;
  spent_usd: number;
  over_soft_budget: boolean;
}

// CustomerOwner/Auditor only (authorize_view_ai_budget) — a plain member
// gets 403, so callers should swallow the error like every other
// optional, role-gated section on this page (archived workspaces, audit).
export function getAiBudgetStatus(sessionId: string, customerId: string): Promise<AiBudgetStatusOut> {
  return apiFetch(`/v1/customers/${customerId}/ai-budget`, sessionId);
}

// ---- browser-side download helper (FR-CTL-002 export, FR-AUD-005 evidence package) ----

// Shared by sessions/page.tsx's "export my data" and customers/[id]/page.tsx's
// "export evidence package" — both fetched a JSON payload and immediately
// saved it as a file with the identical Blob/createObjectURL/anchor-click/
// revokeObjectURL sequence; consolidated here so a third caller doesn't
// have to copy it a third time.
export function downloadJsonFile(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
