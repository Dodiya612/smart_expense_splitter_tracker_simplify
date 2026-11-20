/**
 * Remembers an invite link opened while logged out (T-29 / US-17), so that
 * after login or signup the user lands on the join screen instead of Home.
 *
 * In-memory only: the code is short-lived and not a secret worth persisting.
 */

import { joinPath, normalizeJoinCode } from './joinCode';

let pendingCode: string | null = null;

export function setPendingJoinCode(code: string): void {
  const normalized = normalizeJoinCode(code);
  pendingCode = normalized.length > 0 ? normalized : null;
}

/** Returns the join route for a remembered code and forgets it, or null. */
export function consumePendingJoinPath(): string | null {
  if (!pendingCode) return null;
  const path = joinPath(pendingCode);
  pendingCode = null;
  return path;
}
