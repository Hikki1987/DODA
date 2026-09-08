"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, listMySessions, revokeSession, type SessionOut } from "@/lib/api";
import { useSession } from "@/lib/useSession";

export default function SessionsPage() {
  const sessionId = useSession();
  const [sessions, setSessions] = useState<SessionOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (sessionId === null) return;
    listMySessions(sessionId)
      .then(setSessions)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Yuklab bo'lmadi."));
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleRevoke(target: SessionOut) {
    if (sessionId === null) return;
    try {
      await revokeSession(sessionId, target.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sessiyani yopib bo'lmadi.");
    }
  }

  if (sessionId === null) return null;

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 p-6">
      <div>
        <Link href="/workspaces" className="text-sm text-gray-500 hover:text-black">
          &larr; Workspace&apos;lar
        </Link>
      </div>

      <h1 className="text-xl font-semibold">Faol sessiyalar</h1>
      <p className="text-sm text-gray-500">
        Boshqa qurilma/brauzerdagi sessiyani shu yerdan uzoqdan yopishingiz mumkin (FR-CTL-002). Joriy
        sessiyani chiqish uchun workspace&apos;lar sahifasidagi &quot;Chiqish&quot;ni ishlating.
      </p>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <ul className="space-y-2">
        {sessions?.map((session) => (
          <li
            key={session.id}
            className="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2 text-sm"
          >
            <div>
              <div className="flex items-center gap-2">
                <span>{new Date(session.created_at).toLocaleString()}</span>
                {session.is_current && (
                  <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">joriy</span>
                )}
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                  {session.auth_strength}
                </span>
              </div>
              <div className="text-xs text-gray-500">
                oxirgi faollik: {new Date(session.last_seen_at).toLocaleString()}
              </div>
            </div>
            {!session.is_current && (
              <button onClick={() => handleRevoke(session)} className="text-xs text-red-600 hover:underline">
                Yopish
              </button>
            )}
          </li>
        ))}
        {sessions !== null && sessions.length === 0 && (
          <p className="text-sm text-gray-500">Faol sessiya yo&apos;q.</p>
        )}
      </ul>
    </main>
  );
}
