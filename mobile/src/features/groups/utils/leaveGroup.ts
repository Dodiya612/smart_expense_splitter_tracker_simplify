/**
 * Leave group rules (T-35 / US-22). Pure; unit-tested.
 *
 * Net balance sign follows ledger.md: positive = others owe you, negative = you owe.
 * Any non-zero balance means a warning (with a settle-up shortcut) comes first.
 */

import { formatPaise } from '@/utils/money';

export type LeaveCheck =
  | { kind: 'settled' }
  | { kind: 'you_owe'; amountPaise: number }
  | { kind: 'owed_to_you'; amountPaise: number };

export function leaveCheckFor(netBalancePaise: number): LeaveCheck {
  if (netBalancePaise < 0) return { kind: 'you_owe', amountPaise: -netBalancePaise };
  if (netBalancePaise > 0) return { kind: 'owed_to_you', amountPaise: netBalancePaise };
  return { kind: 'settled' };
}

export interface LeaveDialogText {
  title: string;
  message: string;
}

export function leaveDialogText(check: LeaveCheck, groupName: string): LeaveDialogText {
  const keepHistory = 'Past expenses stay in the group history.';
  switch (check.kind) {
    case 'you_owe':
      return {
        title: 'You still owe money',
        message:
          `You owe ${formatPaise(check.amountPaise)} in "${groupName}". ` +
          'Settle up before you leave. Once you leave, nobody in the group can record a settlement with you. ' +
          keepHistory,
      };
    case 'owed_to_you':
      return {
        title: 'You are still owed money',
        message:
          `Others owe you ${formatPaise(check.amountPaise)} in "${groupName}". ` +
          'Settle up before you leave, or you may not get it back through the app. ' +
          keepHistory,
      };
    default:
      return {
        title: `Leave "${groupName}"?`,
        message: `You won't see new expenses or be added to them. ${keepHistory} You can rejoin later with an invite code.`,
      };
  }
}

/** Plain messages for leave errors from the backend. */
export function leaveErrorMessage(code: string, fallback: string): string {
  switch (code) {
    case 'CANNOT_REMOVE_OWNER':
      return "The group owner can't leave the group.";
    case 'GROUP_ACCESS_DENIED':
    case 'MEMBER_NOT_FOUND':
      return 'You are no longer a member of this group.';
    case 'NOT_FOUND':
    case 'GROUP_NOT_FOUND':
      return 'This group no longer exists.';
    default:
      return fallback;
  }
}
