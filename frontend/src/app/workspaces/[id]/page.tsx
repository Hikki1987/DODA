"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ApiError,
  archiveWorkspace,
  changeTaskStatus,
  changeWorkspaceMemberRole,
  createTask,
  getTaskHistory,
  getWorkspaceKillSwitch,
  listActions,
  listNotifications,
  listTasks,
  listWorkspaceAudit,
  listWorkspaceMembers,
  markNotificationRead,
  removeWorkspaceMember,
  type ActionOut,
  type AuditEventOut,
  type KillSwitchStatusOut,
  type NotificationOut,
  type TaskHistoryEntryOut,
  type TaskOut,
  type TaskStatus,
  type WorkspaceMemberOut,
  type WorkspaceRole,
} from "@/lib/api";
import { useSession } from "@/lib/useSession";

const NEXT_STATUS: Partial<Record<TaskStatus, TaskStatus>> = {
  TODO: "IN_PROGRESS",
  IN_PROGRESS: "DONE",
};

const OTHER_ROLE: Record<WorkspaceRole, WorkspaceRole> = {
  member: "workspace_admin",
  workspace_admin: "member",
};

export default function WorkspacePage() {
  const params = useParams<{ id: string }>();
  const workspaceId = params.id;
  const sessionId = useSession();
  const router = useRouter();

  const [killSwitch, setKillSwitch] = useState<KillSwitchStatusOut | null>(null);
  const [tasks, setTasks] = useState<TaskOut[] | null>(null);
  const [actions, setActions] = useState<ActionOut[] | null>(null);
  const [notifications, setNotifications] = useState<NotificationOut[] | null>(null);
  const [members, setMembers] = useState<WorkspaceMemberOut[] | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEventOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [creatingTask, setCreatingTask] = useState(false);
  const [archivingWorkspace, setArchivingWorkspace] = useState(false);
  const [openTaskHistory, setOpenTaskHistory] = useState<Record<string, TaskHistoryEntryOut[]>>({});

  const refresh = useCallback(() => {
    if (sessionId === null) return;
    getWorkspaceKillSwitch(sessionId, workspaceId).then(setKillSwitch).catch(() => {});
    listTasks(sessionId, workspaceId)
      .then(setTasks)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Yuklab bo'lmadi."));
    listActions(sessionId, workspaceId).then(setActions).catch(() => {});
    listNotifications(sessionId, workspaceId).then(setNotifications).catch(() => {});
    listWorkspaceMembers(sessionId, workspaceId).then(setMembers).catch(() => {});
    listWorkspaceAudit(sessionId, workspaceId).then(setAuditEvents).catch(() => {});
  }, [sessionId, workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreateTask(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || newTaskTitle.trim().length === 0 || creatingTask) return;
    setCreatingTask(true);
    try {
      await createTask(sessionId, workspaceId, newTaskTitle.trim());
      setNewTaskTitle("");
      refresh();
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
        <button
          onClick={handleArchiveWorkspace}
          disabled={archivingWorkspace}
          className="text-xs text-red-600 hover:underline disabled:opacity-50"
        >
          Workspace&apos;ni arxivlash
        </button>
      </div>

      {killSwitch?.engaged && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          <strong>Kill switch faol.</strong> Sabab: {killSwitch.reason}. Yangi action&apos;lar bloklangan.
        </div>
      )}

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
          <button
            type="submit"
            disabled={newTaskTitle.trim().length === 0 || creatingTask}
            className="rounded-md bg-black px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Qo&apos;shish
          </button>
        </form>
        <ul className="space-y-2">
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
        <ul className="space-y-2">
          {auditEvents?.map((event) => (
            <li key={event.id} className="rounded-md border border-gray-200 px-3 py-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium">{event.event_type}</span>
                <span className="text-xs text-gray-500">
                  {new Date(event.occurred_at).toLocaleString()}
                </span>
              </div>
              <div className="text-xs text-gray-500">{event.actor_id}</div>
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
