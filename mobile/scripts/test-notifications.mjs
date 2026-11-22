import test from 'node:test';
import assert from 'node:assert';
import {
  appendUnique,
  badgeLabel,
  formatRelativeTime,
  mapNotification,
  mapNotificationPage,
  mapPreferences,
  mapUnreadCount,
  notificationTarget,
  preferenceLabel,
} from '../src/features/notifications/utils/parseNotifications.ts';
import {
  reconcilePending,
  setReadState,
  shouldMarkRead,
} from '../src/features/notifications/utils/readState.ts';
import { NOTIFICATION_KINDS } from '../src/features/notifications/types.ts';
import {
  mockNotificationsGet,
  mockNotificationsPatch,
  mockNotificationsPut,
} from '../src/services/mock/mockNotifications.ts';

const wire = {
  id: 'n1',
  kind: 'group_expense_created',
  title: 'New expense in Goa Trip',
  body: 'Blair added Dinner (₹2,400).',
  payload: { group_name: 'Goa Trip', amount_paise: 240000 },
  group_id: 'g1',
  is_read: false,
  read_at: null,
  created_at: '2026-11-19T10:00:00+00:00',
};

test('T-36: a wire notification maps to the app shape with read state', () => {
  const item = mapNotification(wire);
  assert.deepStrictEqual(item, {
    id: 'n1',
    kind: 'group_expense_created',
    title: 'New expense in Goa Trip',
    body: 'Blair added Dinner (₹2,400).',
    groupId: 'g1',
    groupName: 'Goa Trip',
    isRead: false,
    createdAt: '2026-11-19T10:00:00+00:00',
  });
  assert.strictEqual(mapNotification({ ...wire, is_read: true }).isRead, true);
});

test('T-36: malformed responses never throw and read as empty', () => {
  assert.deepStrictEqual(mapNotificationPage(null), { items: [], nextCursor: null, unreadCount: 0 });
  assert.strictEqual(mapNotification(undefined).id, '');
  assert.strictEqual(mapNotification({ ...wire, group_id: null }).groupId, null);
  assert.strictEqual(mapUnreadCount({ unread_count: -3 }), 0);
  assert.strictEqual(mapUnreadCount('nope'), 0);
  assert.deepStrictEqual(mapPreferences({}), []);
});

test('T-36: a page keeps the cursor and the server unread count', () => {
  const page = mapNotificationPage({ items: [wire], next_cursor: 'abc', unread_count: 7 });
  assert.strictEqual(page.items.length, 1);
  assert.strictEqual(page.nextCursor, 'abc');
  assert.strictEqual(page.unreadCount, 7);
});

test('T-36: appending a page never duplicates a notification', () => {
  const a = mapNotification(wire);
  const b = mapNotification({ ...wire, id: 'n2' });
  assert.deepStrictEqual(appendUnique([a], [a, b]).map((n) => n.id), ['n1', 'n2']);
});

test('T-36: the bell badge hides at zero and caps at 99+', () => {
  assert.strictEqual(badgeLabel(0), '');
  assert.strictEqual(badgeLabel(-2), '');
  assert.strictEqual(badgeLabel(7), '7');
  assert.strictEqual(badgeLabel(99), '99');
  assert.strictEqual(badgeLabel(100), '99+');
});

test('T-36: relative time reads naturally', () => {
  const now = new Date('2026-11-19T12:00:00Z');
  assert.strictEqual(formatRelativeTime('2026-11-19T11:59:40Z', now), 'Just now');
  assert.strictEqual(formatRelativeTime('2026-11-19T11:55:00Z', now), '5 min ago');
  assert.strictEqual(formatRelativeTime('2026-11-19T10:00:00Z', now), '2 h ago');
  assert.strictEqual(formatRelativeTime('2026-11-16T12:00:00Z', now), '3 d ago');
  assert.match(formatRelativeTime('2026-10-01T12:00:00Z', now), /^\d{1,2} [A-Z][a-z]{2}$/);
  assert.strictEqual(formatRelativeTime('not a date', now), '');
});

test('T-36: tapping opens the right existing screen', () => {
  const base = mapNotification(wire);
  assert.deepStrictEqual(notificationTarget(base), { pathname: '/groups/[id]', params: { id: 'g1' } });
  assert.deepStrictEqual(notificationTarget({ ...base, kind: 'settlement_recorded' }), {
    pathname: '/group-balances',
    params: { groupId: 'g1', groupName: 'Goa Trip' },
  });
  // A removed member can no longer open the group; an invitee is not in it yet.
  assert.deepStrictEqual(notificationTarget({ ...base, kind: 'member_removed' }), { pathname: '/(tabs)/groups' });
  assert.deepStrictEqual(notificationTarget({ ...base, kind: 'invitation_received' }), { pathname: '/(tabs)/groups' });
  assert.strictEqual(notificationTarget({ ...base, groupId: null }), null);
});

test('T-36: every notification type has a settings label', () => {
  for (const kind of NOTIFICATION_KINDS) {
    const { label, hint } = preferenceLabel(kind);
    assert.notStrictEqual(label, kind, `${kind} has no label`);
    assert.ok(hint.length > 0);
  }
});

test('T-36 mock: list is newest first, paginates and counts unread', () => {
  const first = mockNotificationsGet('/api/v1/notifications?limit=3');
  assert.strictEqual(first.items.length, 3);
  assert.ok(first.next_cursor);
  const stamps = first.items.map((n) => n.created_at);
  assert.deepStrictEqual(stamps, [...stamps].sort().reverse());
  const rest = mockNotificationsGet(`/api/v1/notifications?limit=3&cursor=${first.next_cursor}`);
  assert.strictEqual(rest.items.length, 1);
  assert.strictEqual(rest.next_cursor, null);
  assert.strictEqual(mockNotificationsGet('/api/v1/notifications/unread-count').unread_count, 2);
});

test('T-36 mock: mark read, mark all read and preferences behave like the API', () => {
  const read = mockNotificationsPatch('/api/v1/notifications/ntf_mock_1/read');
  assert.strictEqual(read.is_read, true);
  assert.strictEqual(mockNotificationsGet('/api/v1/notifications/unread-count').unread_count, 1);
  assert.throws(() => mockNotificationsPatch('/api/v1/notifications/missing/read'), /not found/i);
  assert.deepStrictEqual(mockNotificationsPatch('/api/v1/notifications/read-all'), { updated: 1 });
  assert.strictEqual(mockNotificationsGet('/api/v1/notifications/unread-count').unread_count, 0);

  const saved = mockNotificationsPut('/api/v1/notification-preferences', {
    preferences: [{ kind: 'member_joined', enabled: false }],
  });
  assert.strictEqual(saved.preferences.find((p) => p.kind === 'member_joined').enabled, false);
  assert.strictEqual(saved.preferences.find((p) => p.kind === 'member_left').enabled, true);
  assert.throws(
    () => mockNotificationsPut('/api/v1/notification-preferences', { preferences: [{ kind: 'nope', enabled: false }] })
  );
  assert.strictEqual(mockNotificationsGet('/api/v1/something-else'), undefined);
});

// ---- markRead decision and concurrent refresh handling (T-36 review fix) ----

const unread = (id) => mapNotification({ ...wire, id, is_read: false });
const read = (id) => mapNotification({ ...wire, id, is_read: true });

test('T-36 markRead: only a known unread notification with no request in flight is sent', () => {
  const items = [unread('a'), read('b')];
  assert.strictEqual(shouldMarkRead(items, 'a', new Set()), true);
  assert.strictEqual(shouldMarkRead(items, 'b', new Set()), false); // already read: no API call
  assert.strictEqual(shouldMarkRead(items, 'zzz', new Set()), false); // unknown id
  assert.strictEqual(shouldMarkRead(items, 'a', new Set(['a'])), false); // double tap
  assert.strictEqual(shouldMarkRead(null, 'a', new Set()), false); // nothing loaded yet
});

test('T-36 markRead: the decision comes from the snapshot, not from running an updater', () => {
  // The old code set a flag inside a state updater and read it right after; if the updater
  // ran later, nothing was sent. This decision is a plain function of the list snapshot.
  const snapshot = [unread('a')];
  const decision = shouldMarkRead(snapshot, 'a', new Set());
  const updater = (current) => setReadState(current, 'a', true); // not executed yet
  assert.strictEqual(decision, true);
  assert.strictEqual(snapshot[0].isRead, false);
  assert.strictEqual(updater(snapshot)[0].isRead, true);
});

test('T-36 markRead: setReadState is immutable and leaves other items alone', () => {
  const items = [unread('a'), unread('b')];
  const after = setReadState(items, 'a', true);
  assert.strictEqual(items[0].isRead, false);
  assert.strictEqual(after[0].isRead, true);
  assert.strictEqual(after[1], items[1]);
  assert.strictEqual(setReadState(after, 'a', true)[0], after[0]); // no-op keeps identity
  assert.strictEqual(setReadState(after, 'a', false)[0].isRead, false); // rollback
});

test('T-36 markRead: a refresh answered before the server saved the read does not flicker back', () => {
  // Tap "a" (in flight), then a refresh returns the server list where "a" is still unread.
  const serverPage = [unread('a'), unread('b'), read('c')];
  const { items, unreadAdjustment } = reconcilePending(serverPage, new Set(['a']));
  assert.deepStrictEqual(items.map((n) => n.isRead), [true, false, true]);
  assert.strictEqual(unreadAdjustment, 1);
  // Server unread count was 2 (a, b); the badge shows 1, consistent with the list.
  assert.strictEqual(Math.max(0, 2 - unreadAdjustment), 1);
});

test('T-36 markRead: nothing is adjusted when the server already reports the item read', () => {
  const { items, unreadAdjustment } = reconcilePending([read('a'), unread('b')], new Set(['a']));
  assert.strictEqual(unreadAdjustment, 0);
  assert.deepStrictEqual(items.map((n) => n.isRead), [true, false]);
});

test('T-36 markRead: load-more pages are reconciled the same way and never duplicate rows', () => {
  const first = [unread('a')];
  const next = reconcilePending([unread('b'), unread('a')], new Set(['b']));
  assert.strictEqual(next.unreadAdjustment, 1);
  const merged = appendUnique(first, next.items);
  assert.deepStrictEqual(merged.map((n) => n.id), ['a', 'b']);
  assert.strictEqual(merged[1].isRead, true);
});

test('T-36 markRead: failure sequence restores the item and keeps the count consistent', () => {
  // tap -> optimistic read -> request fails -> rollback + count restored.
  let items = [unread('a'), unread('b')];
  let count = 2;
  const pending = new Set();
  assert.strictEqual(shouldMarkRead(items, 'a', pending), true);
  pending.add('a');
  items = setReadState(items, 'a', true);
  count = Math.max(0, count - 1);
  assert.strictEqual(count, 1);
  // request fails
  pending.delete('a');
  items = setReadState(items, 'a', false);
  count += 1;
  assert.strictEqual(count, 2);
  assert.strictEqual(items.filter((n) => !n.isRead).length, count);
  // and the user can retry
  assert.strictEqual(shouldMarkRead(items, 'a', pending), true);
});
