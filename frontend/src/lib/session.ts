// Authorization is a raw session UUID either way — the dev/test form on
// /login (session_service.create_session called directly) and the real
// Google login flow (/auth/callback below) both end up handing this
// module the same shape of value: a Session row's id, not a signed JWT
// (see backend CLAUDE.md's known limitation on api/dependencies.py —
// "Bearer <session-id>" is unsigned). Nothing here needs to know which
// path produced it.

const STORAGE_KEY = "doda.sessionId";

export function getStoredSessionId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeSessionId(sessionId: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, sessionId);
  } catch {
    // Private browsing / storage disabled — the session simply won't
    // persist across reloads; nothing else to do about it client-side.
  }
}

export function clearStoredSessionId(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // See storeSessionId.
  }
}
