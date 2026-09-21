"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { getStoredSessionId } from "@/lib/session";

function subscribe(): () => void {
  // localStorage has no reliable same-tab change event; this MVP shell
  // only needs the value once per navigation, not live cross-tab sync.
  return () => {};
}

// `undefined` — never a real getStoredSessionId() result — marks "not
// resolved yet" (server render, and the first client render, which must
// match it to avoid a hydration mismatch) as distinct from a *confirmed*
// absent session (`null`, only ever produced by the real client snapshot).
// The redirect effect below only ever fires on that confirmed `null`.
//
// This distinction is the fix for a real bug: a plain `getServerSnapshot
// = () => null` (this hook's previous version) made the transient
// first-render value indistinguishable from "no session" — on a hard
// reload of an authenticated page, that transient `null` fired the
// redirect to /login and navigated away before React's own hydration
// correction (re-render with the real localStorage value) ever had a
// chance to apply, bouncing an already-logged-in user. Reproduced with a
// real `page.reload()` against a valid session (redirected to /login
// before this fix, stayed put after) — see CLAUDE.md.
function getServerSnapshot(): string | null | undefined {
  return undefined;
}

/** Every authenticated page needs this same guard: no stored session id ->
 * back to /login. */
export function useSession(): string | null {
  const router = useRouter();
  const sessionId = useSyncExternalStore(subscribe, getStoredSessionId, getServerSnapshot);

  useEffect(() => {
    if (sessionId === null) {
      router.replace("/login");
    }
  }, [sessionId, router]);

  return sessionId ?? null;
}
