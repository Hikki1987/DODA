"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ApiError,
  archiveWorkspace,
  cancelTaskReminder,
  changeTaskStatus,
  changeWorkspaceMemberRole,
  confirmTaskReminder,
  createTask,
  disengageWorkspaceKillSwitch,
  engageWorkspaceKillSwitch,
  getTaskDecisions,
  getTaskHistory,
  getTaskPlan,
  getTaskReminders,
  getWorkspaceKillSwitch,
  listActions,
  listNotifications,
  listTasks,
  listWorkspaceAudit,
  listWorkspaceMembers,
  markNotificationRead,
  recordTaskDecision,
  removeWorkspaceMember,
  requestTaskReminder,
  type ActionOut,
  type AuditEventOut,
  type KillSwitchStatusOut,
  type NotificationOut,
  type ReminderOut,
  type TaskDecisionOut,
  type TaskHistoryEntryOut,
  type TaskOut,
  type TaskPlanPeriod,
  type TaskStatus,
  type WorkspaceMemberOut,
  type WorkspaceRole,
} from "@/lib/api";
import { KillSwitchPanel } from "@/components/KillSwitchPanel";
import { useSession } from "@/lib/useSession";

const NEXT_STATUS: Partial<Record<TaskStatus, TaskStatus>> = {
  TODO: "IN_PROGRESS",
  IN_PROGRESS: "DONE",
};

const OTHER_ROLE: Record<WorkspaceRole, WorkspaceRole> = {
  member: "workspace_admin",
  workspace_admin: "member",
};

interface DecisionDraft {
  variant: string;
  tradeoff: string;
  decision: string;
  reason: string;
}

const EMPTY_DECISION_DRAFT: DecisionDraft = { variant: "", tradeoff: "", decision: "", reason: "" };

export default function WorkspacePage() {
  const params = useParams<{ id: string }>();
  const workspaceId = params.id;
  const sessionId = useSession();
  const router = useRouter();

  const [killSwitch, setKillSwitch] = useState<KillSwitchStatusOut | null>(null);
  const [killSwitchReason, setKillSwitchReason] = useState("");
  const [engagingKillSwitch, setEngagingKillSwitch] = useState(false);
  const [tasks, setTasks] = useState<TaskOut[] | null>(null);
  const [actions, setActions] = useState<ActionOut[] | null>(null);
  const [notifications, setNotifications] = useState<NotificationOut[] | null>(null);
  const [members, setMembers] = useState<WorkspaceMemberOut[] | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEventOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskDueDate, setNewTaskDueDate] = useState("");
  const [creatingTask, setCreatingTask] = useState(false);
  const [planPeriod, setPlanPeriod] = useState<TaskPlanPeriod>("daily");
  const [plan, setPlan] = useState<TaskOut[] | null>(null);
  const [archivingWorkspace, setArchivingWorkspace] = useState(false);
  const [openTaskHistory, setOpenTaskHistory] = useState<Record<string, TaskHistoryEntryOut[]>>({});
  const [openTaskDecisions, setOpenTaskDecisions] = useState<Record<string, TaskDecisionOut[]>>({});
  const [decisionDrafts, setDecisionDrafts] = useState<Record<string, DecisionDraft>>({});
  const [recordingDecisionFor, setRecordingDecisionFor] = useState<string | null>(null);
  const [openTaskReminders, setOpenTaskReminders] = useState<Record<string, ReminderOut[]>>({});
  const [reminderDrafts, setReminderDrafts] = useState<Record<string, string>>({});
  const [requestingReminderFor, setRequestingReminderFor] = useState<string | null>(null);
  const [traceIdInput, setTraceIdInput] = useState("");
  const [appliedTraceId, setAppliedTraceId] = useState("");

  const refresh = useCallback(() => {
    if (sessionId === null) return;
    getWorkspaceKillSwitch(sessionId, workspaceId).then(setKillSwitch).catch(() => {});
    listTasks(sessionId, workspaceId)
      .then(setTasks)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Yuklab bo'lmadi."));
    listActions(sessionId, workspaceId).then(setActions).catch(() => {});
    listNotifications(sessionId, workspaceId).then(setNotifications).catch(() => {});
    listWorkspaceMembers(sessionId, workspaceId).then(setMembers).catch(() => {});
    listWorkspaceAudit(sessionId, workspaceId, appliedTraceId || undefined)
      .then(setAuditEvents)
      .catch(() => {});
  }, [sessionId, workspaceId, appliedTraceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const refreshPlan = useCallback(() => {
    if (sessionId === null) return;
    getTaskPlan(sessionId, workspaceId, planPeriod)
      .then(setPlan)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Rejani yuklab bo'lmadi."));
  }, [sessionId, workspaceId, planPeriod]);

  useEffect(() => {
    refreshPlan();
  }, [refreshPlan]);

  async function handleCreateTask(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || newTaskTitle.trim().length === 0 || creatingTask) return;
    setCreatingTask(true);
    try {
      // <input type="datetime-local"> has no timezone of its own — treated
      // as local time, which Date's own constructor already assumes, so
      // toISOString() below correctly converts it to UTC for the backend.
      const dueDate = newTaskDueDate.trim().length > 0 ? new Date(newTaskDueDate).toISOString() : null;
      await createTask(sessionId, workspaceId, newTaskTitle.trim(), dueDate);
      setNewTaskTitle("");
      setNewTaskDueDate("");
      refresh();
      refreshPlan();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Task yaratib bo'lmadi.");
    } finally {
      setCreatingTask(false);
    }
  }

  async function handleAdvanceTask(task: TaskOut) {
    if (sessionId === null) return;
    const next = NEXT_STATUS[task.status];
    if (!next) return;
    try {
      await changeTaskStatus(sessionId, workspaceId, task.id, next);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Task holatini o'zgartirib bo'lmadi.");
    }
  }

  async function toggleTaskHistory(task: TaskOut) {
    if (sessionId === null) return;
    if (openTaskHistory[task.id] !== undefined) {
      setOpenTaskHistory((prev) => {
        const next = { ...prev };
        delete next[task.id];
        return next;
      });
      return;
    }
    try {
      const history = await getTaskHistory(sessionId, workspaceId, task.id);
      setOpenTaskHistory((prev) => ({ ...prev, [task.id]: history }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Tarixni yuklab bo'lmadi.");
    }
  }

  async function toggleTaskDecisions(task: TaskOut) {
    if (sessionId === null) return;
    if (openTaskDecisions[task.id] !== undefined) {
      setOpenTaskDecisions((prev) => {
        const next = { ...prev };
        delete next[task.id];
        return next;
      });
      return;
    }
    try {
      const decisions = await getTaskDecisions(sessionId, workspaceId, task.id);
      setOpenTaskDecisions((prev) => ({ ...prev, [task.id]: decisions }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Qarorlarni yuklab bo'lmadi.");
    }
  }

  function updateDecisionDraft(taskId: string, field: keyof DecisionDraft, value: string) {
    setDecisionDrafts((prev) => ({
      ...prev,
      [taskId]: { ...(prev[taskId] ?? EMPTY_DECISION_DRAFT), [field]: value },
    }));
  }

  async function handleRecordDecision(task: TaskOut) {
    if (sessionId === null || recordingDecisionFor !== null) return;
    const draft = decisionDrafts[task.id] ?? EMPTY_DECISION_DRAFT;
    if (![draft.variant, draft.tradeoff, draft.decision, draft.reason].every((v) => v.trim().length > 0)) {
      return;
    }
    setRecordingDecisionFor(task.id);
    try {
      // FR-TASK-003: this always inserts a new version, it never edits an
      // earlier decision — re-fetching below shows the full history,
      // oldest first, including the one just recorded.
      await recordTaskDecision(sessionId, workspaceId, task.id, draft);
      setDecisionDrafts((prev) => ({ ...prev, [task.id]: EMPTY_DECISION_DRAFT }));
      const decisions = await getTaskDecisions(sessionId, workspaceId, task.id);
      setOpenTaskDecisions((prev) => ({ ...prev, [task.id]: decisions }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Qarorni saqlab bo'lmadi.");
    } finally {
      setRecordingDecisionFor(null);
    }
  }

  async function toggleTaskReminders(task: TaskOut) {
    if (sessionId === null) return;
    if (openTaskReminders[task.id] !== undefined) {
      setOpenTaskReminders((prev) => {
        const next = { ...prev };
        delete next[task.id];
        return next;
      });
      return;
    }
    try {
      const reminders = await getTaskReminders(sessionId, workspaceId, task.id);
      setOpenTaskReminders((prev) => ({ ...prev, [task.id]: reminders }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Eslatmalarni yuklab bo'lmadi.");
    }
  }

  async function handleRequestReminder(task: TaskOut) {
    if (sessionId === null || requestingReminderFor !== null) return;
    const remindAt = reminderDrafts[task.id];
    if (!remindAt) return;
    setRequestingReminderFor(task.id);
    try {
      // FR-TASK-005: this only creates a PENDING_CONFIRMATION request —
      // it never fires or notifies anyone until confirmed below.
      await requestTaskReminder(sessionId, workspaceId, task.id, new Date(remindAt).toISOString());
      setReminderDrafts((prev) => ({ ...prev, [task.id]: "" }));
      const reminders = await getTaskReminders(sessionId, workspaceId, task.id);
      setOpenTaskReminders((prev) => ({ ...prev, [task.id]: reminders }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Eslatma so'rovini yuborib bo'lmadi.");
    } finally {
      setRequestingReminderFor(null);
    }
  }

  async function handleConfirmReminder(task: TaskOut, reminder: ReminderOut) {
    if (sessionId === null) return;
    try {
      // Echoes back the reminder's own current remind_at — the exact
      // time is what's being confirmed, not just the id.
      await confirmTaskReminder(sessionId, workspaceId, task.id, reminder.id, reminder.remind_at);
      const reminders = await getTaskReminders(sessionId, workspaceId, task.id);
      setOpenTaskReminders((prev) => ({ ...prev, [task.id]: reminders }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Eslatmani tasdiqlab bo'lmadi.");
    }
  }

  async function handleCancelReminder(task: TaskOut, reminder: ReminderOut) {
    if (sessionId === null) return;
    try {
      await cancelTaskReminder(sessionId, workspaceId, task.id, reminder.id);
      const reminders = await getTaskReminders(sessionId, workspaceId, task.id);
      setOpenTaskReminders((prev) => ({ ...prev, [task.id]: reminders }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Eslatmani bekor qilib bo'lmadi.");
    }
  }

  async function handleToggleMemberRole(member: WorkspaceMemberOut) {
    if (sessionId === null || member.membership_id === null) return;
    try {
      await changeWorkspaceMemberRole(
        sessionId,
        workspaceId,
        member.membership_id,
        OTHER_ROLE[member.role as WorkspaceRole],
      );
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Rolni o'zgartirib bo'lmadi.");
    }
  }

  async function handleRemoveMember(member: WorkspaceMemberOut) {
    if (sessionId === null || member.membership_id === null) return;
    try {
      await removeWorkspaceMember(sessionId, workspaceId, member.membership_id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "A'zoni chiqarib bo'lmadi.");
    }
  }

  async function handleMarkRead(notification: NotificationOut) {
    if (sessionId === null) return;
    await markNotificationRead(sessionId, workspaceId, notification.id).catch(() => {});
    refresh();
  }

  async function handleEngageKillSwitch(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || killSwitchReason.trim().length === 0 || engagingKillSwitch) return;
    setEngagingKillSwitch(true);
    try {
      await engageWorkspaceKillSwitch(sessionId, workspaceId, killSwitchReason.trim());
      setKillSwitchReason("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kill switch'ni yoqib bo'lmadi.");
    } finally {
      setEngagingKillSwitch(false);
    }
  }

  async function handleDisengageKillSwitch() {
    if (sessionId === null) return;
    try {
      await disengageWorkspaceKillSwitch(sessionId, workspaceId);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kill switch'ni o'chirib bo'lmadi.");
    }
  }

  async function handleArchiveWorkspace() {
    if (sessionId === null || archivingWorkspace) return;
    // Archiving removes this workspace from GET /v1/me/workspaces and this
    // page immediately denies access to it (get_workspace_context) — the
    // only way back is the customer page's "Arxivlangan workspace'lar"
    // list, so this needs an explicit, unmissable confirmation up front.
    if (!window.confirm("Bu workspace'ni arxivlashni tasdiqlaysizmi? Uni faqat customer sahifasidan tiklash mumkin bo'ladi.")) {
      return;
    }
    setArchivingWorkspace(true);
    try {
      await archiveWorkspace(sessionId, workspaceId);
      router.replace("/workspaces");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Workspace'ni arxivlab bo'lmadi.");
      setArchivingWorkspace(false);
    }
  }

  if (sessionId === null) return null;

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-8 p-6">
      <div className="flex items-center justify-between">
        <Link href="/workspaces" className="text-sm text-gray-500 hover:text-black">
          &larr; Workspace&apos;lar
        </Link>
        <div className="flex items-center gap-4">
          <Link href={`/workspaces/${workspaceId}/chat`} className="text-xs text-blue-600 hover:underline">
            Chat
          </Link>
          <button
            onClick={handleArchiveWorkspace}
            disabled={archivingWorkspace}
            className="text-xs text-red-600 hover:underline disabled:opacity-50"
          >
            Workspace&apos;ni arxivlash
          </button>
        </div>
      </div>

      <KillSwitchPanel
        killSwitch={killSwitch}
        reason={killSwitchReason}
        onReasonChange={setKillSwitchReason}
        engaging={engagingKillSwitch}
        onEngage={handleEngageKillSwitch}
        onDisengage={handleDisengageKillSwitch}
        blockedNote="Yangi action'lar bloklangan"
      />

      {error && <p className="text-sm text-red-600">{error}</p>}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Task&apos;lar</h2>
        <form onSubmit={handleCreateTask} className="mb-3 flex gap-2">
          <input
            type="text"
            value={newTaskTitle}
            onChange={(event) => setNewTaskTitle(event.target.value)}
            placeholder="Yangi task nomi"
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-black focus:outline-none"
          />
          <input
            type="datetime-local"
            aria-label="Muddat (ixtiyoriy)"
            value={newTaskDueDate}
            onChange={(event) => setNewTaskDueDate(event.target.value)}
            className="rounded-md border border-gray-300 px-2 py-2 text-sm focus:border-black focus:outline-none"
          />
          <button
            type="submit"
            disabled={newTaskTitle.trim().length === 0 || creatingTask}
            className="rounded-md bg-black px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Qo&apos;shish
          </button>
        </form>

        <div data-testid="task-plan" className="mb-4 rounded-md border border-gray-200 p-3">
          <div className="mb-2 flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-700">Reja</h3>
            <select
              aria-label="Reja davri"
              value={planPeriod}
              onChange={(event) => setPlanPeriod(event.target.value as TaskPlanPeriod)}
              className="rounded border border-gray-200 bg-gray-50 px-1 py-1 text-xs"
            >
              <option value="daily">Kunlik</option>
              <option value="weekly">Haftalik</option>
            </select>
          </div>
          <ul className="space-y-1">
            {plan?.map((task) => (
              <li key={task.id} className="flex items-center justify-between text-xs">
                <span>{task.title}</span>
                <span className="text-gray-400">
                  {task.due_date ? new Date(task.due_date).toLocaleString() : ""}
                </span>
              </li>
            ))}
          </ul>
          {plan !== null && plan.length === 0 && (
            <p className="text-xs text-gray-500">Bu davr uchun muddatli task yo&apos;q.</p>
          )}
        </div>
        <ul data-testid="task-list" className="space-y-2">
          {tasks?.map((task) => (
            <li key={task.id} className="rounded-md border border-gray-200 px-3 py-2">
              <div className="flex items-center justify-between">
                <span className={task.status === "DONE" ? "text-gray-400 line-through" : ""}>
                  {task.title}
                </span>
                <div className="flex items-center gap-2">
                  <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                    {task.status}
                  </span>
                  {NEXT_STATUS[task.status] && (
                    <button
                      onClick={() => handleAdvanceTask(task)}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      {NEXT_STATUS[task.status]} qilish
                    </button>
                  )}
                  <button
                    onClick={() => toggleTaskHistory(task)}
                    className="text-xs text-gray-500 hover:underline"
                  >
                    {openTaskHistory[task.id] !== undefined ? "Tarixni yashirish" : "Tarix"}
                  </button>
                  <button
                    onClick={() => toggleTaskDecisions(task)}
                    className="text-xs text-gray-500 hover:underline"
                  >
                    {openTaskDecisions[task.id] !== undefined ? "Qarorlarni yashirish" : "Qarorlar"}
                  </button>
                  <button
                    onClick={() => toggleTaskReminders(task)}
                    className="text-xs text-gray-500 hover:underline"
                  >
                    {openTaskReminders[task.id] !== undefined ? "Eslatmalarni yashirish" : "Eslatmalar"}
                  </button>
                </div>
              </div>
              {openTaskHistory[task.id] !== undefined && (
                <ul className="mt-2 space-y-1 border-t border-gray-100 pt-2">
                  {openTaskHistory[task.id].map((entry) => (
                    <li key={entry.id} className="text-xs text-gray-500">
                      {entry.from_status ?? "—"} &rarr; {entry.to_status} ({entry.actor_id},{" "}
                      {new Date(entry.created_at).toLocaleString()})
                    </li>
                  ))}
                  {openTaskHistory[task.id].length === 0 && (
                    <li className="text-xs text-gray-500">Tarix bo&apos;sh.</li>
                  )}
                </ul>
              )}
              {openTaskDecisions[task.id] !== undefined && (
                <div className="mt-2 space-y-2 border-t border-gray-100 pt-2">
                  <ul className="space-y-1">
                    {openTaskDecisions[task.id].map((entry) => (
                      <li key={entry.id} className="text-xs text-gray-500">
                        <span className="font-medium text-gray-700">{entry.decision}</span> —{" "}
                        {entry.variant} ({entry.actor_id}, {new Date(entry.created_at).toLocaleString()})
                        <div className="text-gray-400">
                          {entry.tradeoff} · {entry.reason}
                        </div>
                      </li>
                    ))}
                    {openTaskDecisions[task.id].length === 0 && (
                      <li className="text-xs text-gray-500">Hali qaror yozilmagan.</li>
                    )}
                  </ul>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      handleRecordDecision(task);
                    }}
                    className="space-y-1"
                  >
                    <input
                      aria-label="Variant"
                      placeholder="Variant"
                      value={decisionDrafts[task.id]?.variant ?? ""}
                      onChange={(event) => updateDecisionDraft(task.id, "variant", event.target.value)}
                      className="w-full rounded border border-gray-200 px-2 py-1 text-xs"
                    />
                    <input
                      aria-label="Kelishuv (tradeoff)"
                      placeholder="Tradeoff"
                      value={decisionDrafts[task.id]?.tradeoff ?? ""}
                      onChange={(event) => updateDecisionDraft(task.id, "tradeoff", event.target.value)}
                      className="w-full rounded border border-gray-200 px-2 py-1 text-xs"
                    />
                    <input
                      aria-label="Qaror"
                      placeholder="Qaror"
                      value={decisionDrafts[task.id]?.decision ?? ""}
                      onChange={(event) => updateDecisionDraft(task.id, "decision", event.target.value)}
                      className="w-full rounded border border-gray-200 px-2 py-1 text-xs"
                    />
                    <input
                      aria-label="Sabab"
                      placeholder="Sabab"
                      value={decisionDrafts[task.id]?.reason ?? ""}
                      onChange={(event) => updateDecisionDraft(task.id, "reason", event.target.value)}
                      className="w-full rounded border border-gray-200 px-2 py-1 text-xs"
                    />
                    <button
                      type="submit"
                      disabled={recordingDecisionFor === task.id}
                      className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                    >
                      Qaror yozish
                    </button>
                  </form>
                </div>
              )}
              {openTaskReminders[task.id] !== undefined && (
                <div className="mt-2 space-y-2 border-t border-gray-100 pt-2">
                  <ul data-testid="reminder-list" className="space-y-1">
                    {openTaskReminders[task.id].map((reminder) => (
                      <li key={reminder.id} className="text-xs text-gray-500">
                        {new Date(reminder.remind_at).toLocaleString()} — {reminder.status}
                        {reminder.status === "PENDING_CONFIRMATION" && (
                          <>
                            {" "}
                            <button
                              onClick={() => handleConfirmReminder(task, reminder)}
                              className="text-blue-600 hover:underline"
                            >
                              Tasdiqlash
                            </button>{" "}
                            <button
                              onClick={() => handleCancelReminder(task, reminder)}
                              className="text-red-600 hover:underline"
                            >
                              Bekor qilish
                            </button>
                          </>
                        )}
                        {reminder.status === "CONFIRMED" && (
                          <>
                            {" "}
                            <button
                              onClick={() => handleCancelReminder(task, reminder)}
                              className="text-red-600 hover:underline"
                            >
                              Bekor qilish
                            </button>
                          </>
                        )}
                      </li>
                    ))}
                    {openTaskReminders[task.id].length === 0 && (
                      <li className="text-xs text-gray-500">Hali eslatma yo&apos;q.</li>
                    )}
                  </ul>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      handleRequestReminder(task);
                    }}
                    className="flex items-center gap-2"
                  >
                    <input
                      aria-label="Eslatma vaqti"
                      type="datetime-local"
                      value={reminderDrafts[task.id] ?? ""}
                      onChange={(event) =>
                        setReminderDrafts((prev) => ({ ...prev, [task.id]: event.target.value }))
                      }
                      className="rounded border border-gray-200 px-2 py-1 text-xs"
                    />
                    <button
                      type="submit"
                      disabled={requestingReminderFor === task.id || !reminderDrafts[task.id]}
                      className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                    >
                      Eslatma so&apos;rash
                    </button>
                  </form>
                </div>
              )}
            </li>
          ))}
          {tasks !== null && tasks.length === 0 && (
            <li className="text-sm text-gray-500">Hali task yo&apos;q.</li>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Action&apos;lar</h2>
        <ul className="space-y-2">
          {actions?.map((action) => (
            <li
              key={action.id}
              className="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2 text-sm"
            >
              <div className="flex flex-col">
                <span>{action.tool_name}</span>
                <span className="text-xs text-gray-500">risk: {action.risk_level}</span>
              </div>
              <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{action.status}</span>
            </li>
          ))}
          {actions !== null && actions.length === 0 && (
            <li className="text-sm text-gray-500">Hali action yo&apos;q.</li>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Bildirishnomalar</h2>
        <ul className="space-y-2">
          {notifications?.map((notification) => (
            <li
              key={notification.id}
              className="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2 text-sm"
            >
              <span className={notification.read_at ? "text-gray-400" : ""}>
                {notification.notification_type} — {notification.reference_type}
              </span>
              {!notification.read_at && (
                <button
                  onClick={() => handleMarkRead(notification)}
                  className="text-xs text-blue-600 hover:underline"
                >
                  O&apos;qildi deb belgilash
                </button>
              )}
            </li>
          ))}
          {notifications !== null && notifications.length === 0 && (
            <li className="text-sm text-gray-500">Bildirishnoma yo&apos;q.</li>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">A&apos;zolar</h2>
        <ul className="space-y-1">
          {members?.map((member) => (
            <li
              key={member.membership_id ?? member.user_id}
              className="flex items-center justify-between text-sm"
            >
              <span>{member.display_name}</span>
              <div className="flex items-center gap-2">
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{member.role}</span>
                {member.membership_id !== null && (
                  <>
                    <button
                      onClick={() => handleToggleMemberRole(member)}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      {OTHER_ROLE[member.role as WorkspaceRole]} qilish
                    </button>
                    <button
                      onClick={() => handleRemoveMember(member)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Chiqarish
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Audit</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setAppliedTraceId(traceIdInput.trim());
          }}
          className="mb-3 flex gap-2 text-xs"
        >
          <input
            type="text"
            value={traceIdInput}
            onChange={(event) => setTraceIdInput(event.target.value)}
            placeholder="trace_id bo'yicha filtrlash"
            className="flex-1 rounded-md border border-gray-300 px-2 py-1.5 font-mono focus:border-black focus:outline-none"
          />
          <button
            type="submit"
            className="rounded border border-gray-300 px-2 py-1 font-medium text-gray-700"
          >
            Filtr
          </button>
          {appliedTraceId !== "" && (
            <button
              type="button"
              onClick={() => {
                setTraceIdInput("");
                setAppliedTraceId("");
              }}
              className="text-red-600 hover:underline"
            >
              Tozalash
            </button>
          )}
        </form>
        <ul className="space-y-2">
          {auditEvents?.map((event) => (
            <li key={event.id} className="rounded-md border border-gray-200 px-3 py-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium">{event.event_type}</span>
                <span className="text-xs text-gray-500">
                  {new Date(event.occurred_at).toLocaleString()}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span>{event.actor_id}</span>
                <button
                  onClick={() => {
                    setTraceIdInput(event.trace_id);
                    setAppliedTraceId(event.trace_id);
                  }}
                  className="font-mono text-gray-500 hover:text-blue-600 hover:underline"
                  title="Shu trace_id bo'yicha filtrlash"
                >
                  {event.trace_id}
                </button>
              </div>
            </li>
          ))}
          {auditEvents !== null && auditEvents.length === 0 && (
            <li className="text-sm text-gray-500">Audit yozuvi yo&apos;q.</li>
          )}
        </ul>
      </section>
    </main>
  );
}
