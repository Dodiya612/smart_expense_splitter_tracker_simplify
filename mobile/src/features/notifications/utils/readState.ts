/**
 * Pure read-state helpers for the notification list (T-36 / US-38).
 *
 * The hook decides whether to call the server from a snapshot of the list taken when
 * the user taps, never from a value captured inside a React state updater (React may run
 * updaters later, or twice). These helpers hold that logic so it can be unit tested.
 */

import type { NotificationItem } from '../types';

/** True only for a known, unread notification that has no mark-read request in flight. */
export function shouldMarkRead(
  items: readonly NotificationItem[] | null,
  id: string,
  inFlight: ReadonlySet<string>
): boolean {
  if (!items || inFlight.has(id)) return false;
  const item = items.find((n) => n.id === id);
  return item !== undefined && !item.isRead;
}

/** Returns a new list with one notification's read flag set (unchanged list if no change). */
export function setReadState(
  items: readonly NotificationItem[],
  id: string,
  isRead: boolean
): NotificationItem[] {
  return items.map((n) => (n.id === id && n.isRead !== isRead ? { ...n, isRead } : n));
}

/**
 * Applies in-flight local reads on top of a page that arrived from the server meanwhile.
 *
 * A refresh or "load more" that was answered before the server processed our PATCH still
 * lists the item as unread. Marking it read here keeps the UI from flickering back, and
 * `unreadAdjustment` says how much to subtract from the server's unread count so the badge
 * stays consistent. Items the server already reports as read are not counted.
 */
export function reconcilePending(
  incoming: readonly NotificationItem[],
  inFlight: ReadonlySet<string>
): { items: NotificationItem[]; unreadAdjustment: number } {
  let unreadAdjustment = 0;
  const items = incoming.map((n) => {
    if (inFlight.has(n.id) && !n.isRead) {
      unreadAdjustment += 1;
      return { ...n, isRead: true };
    }
    return n;
  });
  return { items, unreadAdjustment };
}
