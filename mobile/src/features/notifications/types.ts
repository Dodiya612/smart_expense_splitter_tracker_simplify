/**
 * Notification centre types (T-36 / US-38).
 *
 * Mirror the backend schemas in backend/openapi.json (snake_case on the wire,
 * mapped to camelCase by utils/parseNotifications.ts).
 */

export const NOTIFICATION_KINDS = [
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

export type NotificationKind = (typeof NOTIFICATION_KINDS)[number];

export interface NotificationItem {
  id: string;
  kind: NotificationKind | string;
  title: string;
  body: string;
  groupId: string | null;
  groupName: string | null;
  isRead: boolean;
  createdAt: string;
}

export interface NotificationPage {
  items: NotificationItem[];
  nextCursor: string | null;
  unreadCount: number;
}

export interface NotificationPreference {
  kind: NotificationKind | string;
  enabled: boolean;
  canDisable: boolean;
}
