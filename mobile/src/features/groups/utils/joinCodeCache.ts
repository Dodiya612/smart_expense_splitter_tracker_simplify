/**
 * Holds the latest plaintext join code per group for this app session (T-29 / US-17).
 *
 * The server stores only a hash, so a code can be shown only right after it was
 * created (group creation or "New invite code"). Keeping it in memory lets the
 * group screen show it after navigating there from the create screen.
 */

import type { JoinCode } from '../types';

const codes = new Map<string, JoinCode>();

export function rememberJoinCode(code: JoinCode): void {
  if (code.groupId && code.code) codes.set(code.groupId, code);
}

export function getRememberedJoinCode(groupId: string): JoinCode | null {
  return codes.get(groupId) ?? null;
}

export function forgetJoinCode(groupId: string): void {
  codes.delete(groupId);
}
