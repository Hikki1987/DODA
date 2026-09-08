// Thin, typed client for the DODA backend (see backend/src/doda/api/*.py).
// No codegen — the backend has no OpenAPI schema export wired up yet, so
// these types are hand-kept in sync with the Pydantic response models.
// Every function takes sessionId explicitly (never reads it from storage
// itself) so server components / tests can call the same functions.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

async function apiFetch<T>(
  path: string,
  sessionId: string,
  init?: RequestInit & { idempotencyKey?: string },
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${sessionId}`,
    ...(init?.body ? { "Content-Type": "application/json" } : {}),
    ...(init?.idempotencyKey ? { "Idempotency-Key": init.idempotencyKey } : {}),
  };

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (response.status === 204) {
    return undefined as T;
  }

  const body = await response.json();

  if (!response.ok) {
    throw new ApiError(
      response.status,
      body.code ?? "UNKNOWN",
      body.message ?? "Noma'lum xato yuz berdi",
      body.trace_id ?? "",
    );
  }

  return body as T;
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

export function createTask(sessionId: string, workspaceId: string, title: string): Promise<TaskOut> {
  return apiFetch(`/v1/workspaces/${workspaceId}/tasks`, sessionId, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
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
}

export function listActions(sessionId: string, workspaceId: string): Promise<ActionOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/actions`, sessionId);
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

export function listWorkspaceAudit(sessionId: string, workspaceId: string): Promise<AuditEventOut[]> {
  return apiFetch(`/v1/workspaces/${workspaceId}/audit`, sessionId);
}

// ---- /v1/customers/{id}/audit ----

export function listCustomerAudit(sessionId: string, customerId: string): Promise<AuditEventOut[]> {
  return apiFetch(`/v1/customers/${customerId}/audit`, sessionId);
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
