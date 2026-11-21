/**
 * Pure helpers for the notification centre (T-36 / US-38): wire mapping, relative
 * time, deep links and settings labels. No React Native imports, so they are unit
 * tested with `npm test`.
 */

import type {
  NotificationItem,
  NotificationKind,
  NotificationPage,
  NotificationPreference,
} from '../types';

type Raw = Record<string, unknown>;

const asRecord = (value: unknown): Raw =>
  value && typeof value === 'object' ? (value as Raw) : {};
const asString = (value: unknown): string => (typeof value === 'string' ? value : '');

export function mapNotification(raw: unknown): NotificationItem {
  const r = asRecord(raw);
  const payload = asRecord(r.payload);
  return {
    id: asString(r.id),
    kind: asString(r.kind),
    title: asString(r.title),
    body: asString(r.body),
    groupId: asString(r.group_id) || null,
    groupName: asString(payload.group_name) || null,
    isRead: r.is_read === true,
    createdAt: asString(r.created_at),
  };
}

export function mapNotificationPage(raw: unknown): NotificationPage {
  const r = asRecord(raw);
  const items = Array.isArray(r.items) ? r.items.map(mapNotification) : [];
  return {
    items,
    nextCursor: asString(r.next_cursor) || null,
    unreadCount: typeof r.unread_count === 'number' ? r.unread_count : 0,
  };
}

export function mapUnreadCount(raw: unknown): number {
  const count = asRecord(raw).unread_count;
  return typeof count === 'number' && count > 0 ? Math.floor(count) : 0;
}

export function mapPreferences(raw: unknown): NotificationPreference[] {
  const list = asRecord(raw).preferences;
  if (!Array.isArray(list)) return [];
  return list.map((p) => {
    const r = asRecord(p);
    return {
      kind: asString(r.kind),
      enabled: r.enabled !== false,
      canDisable: r.can_disable !== false,
    };
  });
}

/** Appends a page to the list without duplicating ids (newest-first order is kept). */
export function appendUnique(
  current: NotificationItem[],
  next: NotificationItem[]
): NotificationItem[] {
  const seen = new Set(current.map((n) => n.id));
  return [...current, ...next.filter((n) => !seen.has(n.id))];
}

/** Badge text: the count up to 99, then "99+". Empty for zero so the badge hides. */
export function badgeLabel(count: number): string {
  if (count <= 0) return '';
  return count > 99 ? '99+' : String(count);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Short relative time: "Just now", "5 min ago", "2 h ago", "3 d ago", then "12 Nov". */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return '';
  const seconds = Math.floor((now.getTime() - then.getTime()) / 1000);
  if (seconds < 60) return 'Just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} d ago`;
  return `${then.getDate()} ${MONTHS[then.getMonth()]}`;
}

/** Where tapping a notification goes. Only routes that exist in the app. */
export type NotificationTarget =
  | { pathname: '/groups/[id]'; params: { id: string } }
  | { pathname: '/group-balances'; params: { groupId: string; groupName?: string } }
  | { pathname: '/(tabs)/groups' }
  | { pathname: '/recurring' }
  | null;

export function notificationTarget(item: NotificationItem): NotificationTarget {
  const kind = item.kind;
  if (kind === 'recurring_expense_upcoming' || kind === 'recurring_expense_skipped') {
    // T-45: "added tomorrow – tap to pause" opens the recurring list.
    return { pathname: '/recurring' };
  }
  if (kind === 'invitation_received' || kind === 'member_removed') {
    // The group is not (or not yet) viewable: the Groups tab is the safe landing place.
    return { pathname: '/(tabs)/groups' };
  }
  if (!item.groupId) return null;
  if (kind === 'settlement_recorded') {
    return {
      pathname: '/group-balances',
      params: { groupId: item.groupId, ...(item.groupName ? { groupName: item.groupName } : {}) },
    };
  }
  return { pathname: '/groups/[id]', params: { id: item.groupId } };
}

const KIND_LABELS: Record<NotificationKind, { label: string; hint: string }> = {
  group_expense_created: { label: 'New group expenses', hint: 'Someone adds an expense to a group you are in' },
  group_expense_updated: { label: 'Edited group expenses', hint: 'Someone changes a group expense' },
  group_expense_deleted: { label: 'Deleted group expenses', hint: 'Someone deletes a group expense' },
  settlement_recorded: { label: 'Settlements', hint: 'A repayment you are part of is recorded' },
  member_joined: { label: 'New members', hint: 'Someone joins one of your groups' },
  invitation_received: { label: 'Invitations', hint: 'You are invited to a group' },
  invitation_accepted: { label: 'Accepted invitations', hint: 'Someone accepts your invitation' },
  invitation_declined: { label: 'Declined invitations', hint: 'Someone declines your invitation' },
  member_removed: { label: 'Removed members', hint: 'You are removed, or an admin removes a member' },
  member_left: { label: 'Members leaving', hint: 'Someone leaves a group you manage' },
  password_changed: { label: 'Password changes', hint: 'Your account password is changed' },
  recurring_expense_upcoming: {
    label: 'Upcoming recurring expenses',
    hint: 'The day before a repeating expense is added',
  },
  recurring_expense_skipped: {
    label: 'Skipped recurring expenses',
    hint: 'A repeating expense could not be added on its date',
  },
};

export function preferenceLabel(kind: string): { label: string; hint: string } {
  return KIND_LABELS[kind as NotificationKind] ?? { label: kind, hint: '' };
}
