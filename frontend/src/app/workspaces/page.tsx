"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, listMyWorkspaces, revokeSession, type MyWorkspaceOut } from "@/lib/api";
import { clearStoredSessionId } from "@/lib/session";
import { useSession } from "@/lib/useSession";

export default function WorkspacesPage() {
  const router = useRouter();
  const sessionId = useSession();
  const [workspaces, setWorkspaces] = useState<MyWorkspaceOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (sessionId === null) return;
    listMyWorkspaces(sessionId)
      .then(setWorkspaces)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Yuklab bo'lmadi."));
  }, [sessionId]);

  async function logOut() {
    // "Chiqish" must actually revoke the session server-side (FR-AUTH-005),
    // not just forget it client-side — otherwise the raw session UUID
    // (Authorization: Bearer <id>) still works via direct API calls until
    // its natural idle/absolute timeout, even after the user believes
    // they've logged out. Clear local storage regardless of whether the
    // revoke call succeeds (e.g. offline) — the user must never be stuck
    // unable to leave the logged-in screen because of a network error.
    if (sessionId !== null) {
      await revokeSession(sessionId, sessionId).catch(() => {});
    }
    clearStoredSessionId();
    router.push("/login");
  }

  if (sessionId === null) return null;

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Mening workspace&apos;larim</h1>
        <div className="flex items-center gap-4">
          <Link href="/sessions" className="text-sm text-gray-500 hover:text-black">
            Sessiyalar
          </Link>
          <button onClick={logOut} className="text-sm text-gray-500 hover:text-black">
            Chiqish
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {workspaces === null && !error && <p className="text-sm text-gray-500">Yuklanmoqda...</p>}
      {workspaces !== null && workspaces.length === 0 && (
        <p className="text-sm text-gray-500">Siz hech qanday workspace&apos;ga a&apos;zo emassiz.</p>
      )}

      <ul className="space-y-2">
        {workspaces?.map((workspace) => (
          <li
            key={workspace.workspace_id}
            className="flex items-center justify-between rounded-md border border-gray-200 px-4 py-3 hover:border-black"
          >
            <Link href={`/workspaces/${workspace.workspace_id}`} className="flex-1">
              <div className="font-medium">{workspace.workspace_name}</div>
            </Link>
            <div className="flex flex-1 items-center justify-end gap-3">
              <Link
                href={`/customers/${workspace.customer_id}`}
                className="text-sm text-gray-500 hover:text-black hover:underline"
              >
                {workspace.customer_name}
              </Link>
              <span className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-600">{workspace.role}</span>
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
