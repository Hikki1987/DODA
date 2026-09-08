"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { getStoredSessionId } from "@/lib/session";

function subscribe(): () => void {
  // localStorage has no reliable same-tab change event; this MVP shell
  // only needs the value once per navigation, not live cross-tab sync.
  return () => {};
}

function getServerSnapshot(): string | null {
  return null;
}

/** Every authenticated page needs this same guard: no stored session id ->
 * back to /login. Returns null on the server and during the first client
 * render (matching, so no hydration mismatch), then the real value once
 * mounted — or triggers the redirect if there isn't one. */
export function useSession(): string | null {
  const router = useRouter();
  const sessionId = useSyncExternalStore(subscribe, getStoredSessionId, getServerSnapshot);

  useEffect(() => {
    if (sessionId === null) {
      router.replace("/login");
    }
  }, [sessionId, router]);

  return sessionId;
}
