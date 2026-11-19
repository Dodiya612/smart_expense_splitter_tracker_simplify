/**
 * MOCK ONLY – notification centre data for EXPO_PUBLIC_USE_MOCK_API=true (T-36 / US-38).
 *
 * Returns the response shapes of the real endpoints (backend/openapi.json, snake_case).
 * In memory, per app session: nothing is saved anywhere and everything resets on reload.
 */

import { ApiError } from '@/services/api/types';

const KINDS = [
  'group_expense_created',
  'group_expense_updated',
  'group_expense_deleted',
  'settlement_recorded',
  'member_joined',
  'invitation_received',
  'invitation_accepted',
  'invitation_declined',
  'member_removed',
  'member_left',
] as const;

interface MockNotification {
  id: string;
  kind: string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  group_id: string | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

const MINUTE = 60 * 1000;
const GROUP_ID = 'grp_mock_goa';

function seed(): MockNotification[] {
  const now = Date.now();
  const make = (
    n: number,
    kind: string,
    title: string,
    body: string,
    minutesAgo: number,
    isRead: boolean
  ): MockNotification => ({
    id: `ntf_mock_${n}`,
    kind,
    title,
    body,
    payload: { group_name: 'Goa Trip' },
    group_id: GROUP_ID,
    is_read: isRead,
    read_at: isRead ? new Date(now - (minutesAgo - 1) * MINUTE).toISOString() : null,
    created_at: new Date(now - minutesAgo * MINUTE).toISOString(),
  });
  return [
    make(1, 'group_expense_created', 'New expense in Goa Trip', 'Blair Menon added Beach shack dinner (₹2,400).', 5, false),
    make(2, 'settlement_recorded', 'Settlement recorded in Goa Trip', 'Casey Iyer recorded a settlement of ₹1,000.', 90, false),
    make(3, 'member_joined', 'New member in Goa Trip', 'Casey Iyer joined the group.', 60 * 26, true),
    make(4, 'group_expense_updated', 'Expense updated in Goa Trip', 'Blair Menon updated Scooter rental (₹1,200).', 60 * 24 * 4, true),
  ];
}

let notifications = seed();
const disabled = new Set<string>();

const unreadCount = () => notifications.filter((n) => !n.is_read).length;

function list(endpoint: string): unknown {
  const params = new URLSearchParams(endpoint.split('?')[1] ?? '');
  const limit = Math.max(1, Math.min(100, Number(params.get('limit')) || 20));
  const start = Number(params.get('cursor')) || 0;
  const sorted = [...notifications].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const items = sorted.slice(start, start + limit);
  const next = start + limit < sorted.length ? String(start + limit) : null;
  return { items, next_cursor: next, unread_count: unreadCount() };
}

function preferences(): unknown {
  return {
    preferences: KINDS.map((kind) => ({ kind, enabled: !disabled.has(kind), can_disable: true })),
  };
}

export function mockNotificationsGet(endpoint: string): unknown {
  const path = endpoint.split('?')[0];
  if (path === '/api/v1/notifications/unread-count') return { unread_count: unreadCount() };
  if (path === '/api/v1/notifications') return list(endpoint);
  if (path === '/api/v1/notification-preferences') return preferences();
  return undefined;
}

export function mockNotificationsPatch(endpoint: string): unknown {
  if (endpoint === '/api/v1/notifications/read-all') {
    let updated = 0;
    notifications = notifications.map((n) => {
      if (n.is_read) return n;
      updated += 1;
      return { ...n, is_read: true, read_at: new Date().toISOString() };
    });
    return { updated };
  }
  const match = endpoint.match(/^\/api\/v1\/notifications\/([^/]+)\/read$/);
  if (!match) return undefined;
  const id = decodeURIComponent(match[1]);
  const found = notifications.find((n) => n.id === id);
  if (!found) throw new ApiError('NOTIFICATION_NOT_FOUND', 'Notification not found.', false);
  if (!found.is_read) {
    found.is_read = true;
    found.read_at = new Date().toISOString();
  }
  return found;
}

export function mockNotificationsPut(endpoint: string, body: unknown): unknown {
  if (endpoint !== '/api/v1/notification-preferences') return undefined;
  const items = (body as { preferences?: { kind?: string; enabled?: boolean }[] } | undefined)?.preferences;
  for (const item of items ?? []) {
    if (!item.kind || !(KINDS as readonly string[]).includes(item.kind)) {
      throw new ApiError('VALIDATION_ERROR', 'Unknown notification kind.', false);
    }
    if (item.enabled === false) disabled.add(item.kind);
    else disabled.delete(item.kind);
  }
  return preferences();
}
