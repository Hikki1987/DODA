"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { API_BASE_URL, ApiError, listMySessions } from "@/lib/api";
import { storeSessionId } from "@/lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [sessionId, setSessionId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      // The only "is this a real, unexpired, unrevoked session" check
      // available client-side: try it against a real endpoint and see if
      // the backend accepts it.
      await listMySessions(sessionId.trim());
      storeSessionId(sessionId.trim());
      router.push("/workspaces");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Backend'ga ulanib bo'lmadi.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <div className="w-full max-w-sm space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">DODA</h1>
          <p className="mt-1 text-sm text-gray-500">Shaxsiy AI operatsion tizimi</p>
        </div>

        <a
          href={`${API_BASE_URL}/v1/auth/google/login`}
          className="flex w-full items-center justify-center rounded-md border border-gray-300 px-3 py-2 text-sm font-medium hover:bg-gray-50"
        >
          Google orqali kirish
        </a>

        <div className="flex items-center gap-2 text-xs text-gray-600">
          <div className="h-px flex-1 bg-gray-200" />
          yoki
          <div className="h-px flex-1 bg-gray-200" />
        </div>

        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <strong>Dev/test kirish.</strong> Bu forma session_service orqali
          to&apos;g&apos;ridan-to&apos;g&apos;ri yaratilgan xom session UUID
          qabul qiladi — real login uchun yuqoridagi &quot;Google orqali
          kirish&quot; tugmasidan foydalaning.
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <label className="block text-sm font-medium" htmlFor="session-id">
            Session ID
          </label>
          <input
            id="session-id"
            name="session-id"
            type="text"
            required
            value={sessionId}
            onChange={(event) => setSessionId(event.target.value)}
            placeholder="00000000-0000-0000-0000-000000000000"
            className="w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm focus:border-black focus:outline-none"
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={submitting || sessionId.trim().length === 0}
            className="w-full rounded-md bg-black px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {submitting ? "Tekshirilmoqda..." : "Kirish"}
          </button>
        </form>
      </div>
    </main>
  );
}
