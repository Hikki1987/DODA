// Dev/test auth seam only — see backend CLAUDE.md's known limitation:
// Authorization is a raw session UUID (session_service.create_session),
// not real OIDC (FR-AUTH-001 is S3 backend work still to come). This
// stores that same raw UUID client-side; there is nothing more to it
// until the backend actually issues signed tokens from a real login flow.

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
