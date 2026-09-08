"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ApiError,
  changeTaskStatus,
  createTask,
  getWorkspaceKillSwitch,
  listNotifications,
  listTasks,
  listWorkspaceMembers,
  markNotificationRead,
  type KillSwitchStatusOut,
  type NotificationOut,
  type TaskOut,
  type TaskStatus,
  type WorkspaceMemberOut,
} from "@/lib/api";
import { useSession } from "@/lib/useSession";

const NEXT_STATUS: Partial<Record<TaskStatus, TaskStatus>> = {
  TODO: "IN_PROGRESS",
  IN_PROGRESS: "DONE",
};

export default function WorkspacePage() {
  const params = useParams<{ id: string }>();
  const workspaceId = params.id;
  const sessionId = useSession();

  const [killSwitch, setKillSwitch] = useState<KillSwitchStatusOut | null>(null);
  const [tasks, setTasks] = useState<TaskOut[] | null>(null);
  const [notifications, setNotifications] = useState<NotificationOut[] | null>(null);
  const [members, setMembers] = useState<WorkspaceMemberOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTaskTitle, setNewTaskTitle] = useState("");

  const refresh = useCallback(() => {
    if (sessionId === null) return;
    getWorkspaceKillSwitch(sessionId, workspaceId).then(setKillSwitch).catch(() => {});
    listTasks(sessionId, workspaceId)
      .then(setTasks)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Yuklab bo'lmadi."));
    listNotifications(sessionId, workspaceId).then(setNotifications).catch(() => {});
    listWorkspaceMembers(sessionId, workspaceId).then(setMembers).catch(() => {});
  }, [sessionId, workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreateTask(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || newTaskTitle.trim().length === 0) return;
    try {
      await createTask(sessionId, workspaceId, newTaskTitle.trim());
      setNewTaskTitle("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Task yaratib bo'lmadi.");
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

  async function handleMarkRead(notification: NotificationOut) {
    if (sessionId === null) return;
    await markNotificationRead(sessionId, workspaceId, notification.id).catch(() => {});
    refresh();
  }

  if (sessionId === null) return null;

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-8 p-6">
      <div>
        <Link href="/workspaces" className="text-sm text-gray-500 hover:text-black">
          &larr; Workspace&apos;lar
        </Link>
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
            disabled={newTaskTitle.trim().length === 0}
            className="rounded-md bg-black px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Qo&apos;shish
          </button>
        </form>
        <ul className="space-y-2">
          {tasks?.map((task) => (
            <li
              key={task.id}
              className="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2"
            >
              <span className={task.status === "DONE" ? "text-gray-400 line-through" : ""}>
                {task.title}
              </span>
              <div className="flex items-center gap-2">
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{task.status}</span>
                {NEXT_STATUS[task.status] && (
                  <button
                    onClick={() => handleAdvanceTask(task)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    {NEXT_STATUS[task.status]} qilish
                  </button>
                )}
              </div>
            </li>
          ))}
          {tasks !== null && tasks.length === 0 && (
            <p className="text-sm text-gray-500">Hali task yo&apos;q.</p>
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
            <p className="text-sm text-gray-500">Bildirishnoma yo&apos;q.</p>
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
              <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{member.role}</span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
