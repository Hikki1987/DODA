"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, listMySessions } from "@/lib/api";
import { storeSessionId } from "@/lib/session";

// The one thing this page exists for: the backend's real Google login
// flow (api/auth.py's /v1/auth/google/callback) redirects the browser
// here with ?session_id=<uuid> once it has minted a real Session row —
// this is the client-side half of that handoff, storing the same raw
// session UUID the dev/test /login form stores (see session.ts).
export default function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Read synchronously at render time rather than inside the effect, so
  // the "missing session_id" case needs no setState call at all — same
  // sentinel-value-over-extra-state approach useSession.ts already
  // established for avoiding react-hooks/set-state-in-effect.
  const sessionId = searchParams.get("session_id");
  const [asyncError, setAsyncError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        // Same "is this really a live session" check the dev/test login
        // form does — confirms the backend's own redirect handed us
        // something real before trusting it client-side.
        await listMySessions(sessionId);
        if (!cancelled) {
          storeSessionId(sessionId);
          router.replace("/workspaces");
        }
      } catch (err) {
        if (!cancelled) {
          setAsyncError(err instanceof ApiError ? err.message : "Backend'ga ulanib bo'lmadi.");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sessionId, router]);

  const error = sessionId ? asyncError : "session_id parametri topilmadi. Qaytadan urinib ko'ring.";

  if (error) {
    return (
      <div className="w-full max-w-sm space-y-3 text-center">
        <p className="text-sm text-red-600">{error}</p>
        <a href="/login" className="text-sm font-medium underline">
          Qaytadan kirish
        </a>
      </div>
    );
  }

  return <p className="text-sm text-gray-500">Kirish tasdiqlanmoqda...</p>;
}
