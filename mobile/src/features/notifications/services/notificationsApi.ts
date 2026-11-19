/**
 * Notification centre API (T-36 / US-38). Backend endpoints (backend/openapi.json):
 * - GET   /api/v1/notifications?limit&cursor&unread_only
 * - GET   /api/v1/notifications/unread-count
 * - PATCH /api/v1/notifications/{id}/read
 * - PATCH /api/v1/notifications/read-all
 * - GET   /api/v1/notification-preferences
 * - PUT   /api/v1/notification-preferences
 *
 * The signed-in user comes from the access token; no user id is ever sent.
 * With EXPO_PUBLIC_USE_MOCK_API=true these are served by services/mock/mockNotifications.ts.
 */

import { getApiClient } from '@/services/api/client';
import type { NotificationItem, NotificationPage, NotificationPreference } from '../types';
import {
  mapNotification,
  mapNotificationPage,
  mapPreferences,
  mapUnreadCount,
} from '../utils/parseNotifications';

const BASE = '/api/v1/notifications';
const PREFS = '/api/v1/notification-preferences';
export const PAGE_SIZE = 20;

export async function fetchNotifications(cursor?: string | null): Promise<NotificationPage> {
  const query = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (cursor) query.set('cursor', cursor);
  return mapNotificationPage(await getApiClient().get<unknown>(`${BASE}?${query.toString()}`));
}

export async function fetchUnreadCount(): Promise<number> {
  return mapUnreadCount(await getApiClient().get<unknown>(`${BASE}/unread-count`));
}

export async function markNotificationRead(id: string): Promise<NotificationItem> {
  return mapNotification(
    await getApiClient().patch<unknown>(`${BASE}/${encodeURIComponent(id)}/read`)
  );
}

export async function markAllNotificationsRead(): Promise<void> {
  await getApiClient().patch<unknown>(`${BASE}/read-all`);
}

export async function fetchPreferences(): Promise<NotificationPreference[]> {
  return mapPreferences(await getApiClient().get<unknown>(PREFS));
}

export async function savePreference(
  kind: string,
  enabled: boolean
): Promise<NotificationPreference[]> {
  return mapPreferences(
    await getApiClient().put<unknown>(PREFS, { preferences: [{ kind, enabled }] })
  );
}
