/**
 * Join code helpers for groups (T-29 / US-17).
 *
 * The backend (T-28) issues 8-character codes from the alphabet
 * 23456789ABCDEFGHJKLMNPQRSTUVWXYZ, stores only a hash, and accepts 6–32
 * characters case-insensitively. The share link is /join/<code>.
 *
 * Pure functions only: no React, no network. Unit-tested in scripts/test-groups.mjs.
 */

export const JOIN_CODE_MIN_LENGTH = 6;
export const JOIN_CODE_MAX_LENGTH = 32;

/** Uppercases and strips spaces and dashes, so "abcd-1234" and "ABCD 1234" both work. */
export function normalizeJoinCode(input: string): string {
  return input.replace(/[\s-]/g, '').toUpperCase();
}

/**
 * Pulls a join code out of whatever the user pasted: a bare code, or a full
 * invite link such as "mobile://join/ABCD2345" or "exp://host:8081/--/join/ABCD2345".
 */
export function extractJoinCode(input: string): string {
  const trimmed = input.trim();
  const match = trimmed.match(/\/join\/([A-Za-z0-9-]+)\/?(?:[?#].*)?$/);
  return normalizeJoinCode(match ? match[1] : trimmed);
}

/** Returns an error message for the code, or undefined when it is acceptable. */
export function validateJoinCode(code: string): string | undefined {
  if (code.length === 0) {
    return 'Enter the invite code.';
  }
  if (!/^[A-Z0-9]+$/.test(code)) {
    return 'Use only letters and numbers.';
  }
  if (code.length < JOIN_CODE_MIN_LENGTH || code.length > JOIN_CODE_MAX_LENGTH) {
    return 'Invite codes are 8 characters long.';
  }
  return undefined;
}

/** In-app route path for a join link. */
export function joinPath(code: string): string {
  return `/join/${encodeURIComponent(normalizeJoinCode(code))}`;
}

/** Text shared with other apps when inviting someone. */
export function buildInviteMessage(groupName: string, code: string, link: string): string {
  return [
    `Join "${groupName}" on Coinscious to split expenses with us.`,
    `Invite code: ${code}`,
    `Or open: ${link}`,
    'The code works for 7 days.',
  ].join('\n');
}

/** Maps backend join error codes to plain-language messages. */
export function joinErrorMessage(code: string, fallback: string): string {
  switch (code) {
    case 'INVALID_JOIN_CODE':
      return 'That invite code is not valid. Check it with the person who sent it.';
    case 'JOIN_CODE_EXPIRED':
      return 'That invite code has expired. Ask a group admin for a new one.';
    case 'JOIN_CODE_REVOKED':
      return 'That invite code was turned off. Ask a group admin for a new one.';
    case 'ALREADY_MEMBER':
      return 'You are already a member of this group.';
    case 'NOT_FOUND':
      return 'This group no longer exists.';
    default:
      return fallback;
  }
}
