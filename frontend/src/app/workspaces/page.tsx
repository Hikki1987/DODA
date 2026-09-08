"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, listMyWorkspaces, type MyWorkspaceOut } from "@/lib/api";
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

  function logOut() {
    clearStoredSessionId();
    router.push("/login");
  }

  if (sessionId === null) return null;

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Mening workspace&apos;larim</h1>
        <button onClick={logOut} className="text-sm text-gray-500 hover:text-black">
          Chiqish
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {workspaces === null && !error && <p className="text-sm text-gray-500">Yuklanmoqda...</p>}
      {workspaces !== null && workspaces.length === 0 && (
        <p className="text-sm text-gray-500">Siz hech qanday workspace&apos;ga a&apos;zo emassiz.</p>
      )}

      <ul className="space-y-2">
        {workspaces?.map((workspace) => (
          <li key={workspace.workspace_id}>
            <Link
              href={`/workspaces/${workspace.workspace_id}`}
              className="flex items-center justify-between rounded-md border border-gray-200 px-4 py-3 hover:border-black"
            >
              <div>
                <div className="font-medium">{workspace.workspace_name}</div>
                <div className="text-sm text-gray-500">{workspace.customer_name}</div>
              </div>
              <span className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-600">{workspace.role}</span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
