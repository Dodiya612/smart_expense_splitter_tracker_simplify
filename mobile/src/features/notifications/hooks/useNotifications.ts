/**
 * Notification list state (T-36 / US-38): first page, "load more", pull to refresh,
 * mark one read and mark all read. Reloads on focus and when the app returns to the
 * foreground. Marking read is optimistic and rolled back if the request fails.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/services/api/types';
import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '../services/notificationsApi';
import type { NotificationItem } from '../types';
import { appendUnique } from '../utils/parseNotifications';
import { reconcilePending, setReadState, shouldMarkRead } from '../utils/readState';
import { useRefreshOnActive } from './useRefreshOnActive';

export interface UseNotificationsReturn {
  items: NotificationItem[] | null;
  unreadCount: number;
  isLoading: boolean;
  isRefreshing: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  error: ApiError | null;
  actionError: string | null;
  refresh: () => Promise<void>;
  retry: () => Promise<void>;
  loadMore: () => Promise<void>;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
}

function toApiError(err: unknown, message: string): ApiError {
  return err instanceof ApiError ? err : new ApiError('NOTIFICATIONS_FAILED', message, true);
}

export function useNotifications(): UseNotificationsReturn {
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const loadedRef = useRef(false);
  /** Ids whose mark-read request is in flight (read optimistically, not yet confirmed). */
  const pendingReadRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async (mode: 'initial' | 'refresh' | 'silent') => {
    if (mode === 'initial') setIsLoading(true);
    if (mode === 'refresh') setIsRefreshing(true);
    try {
      const page = await fetchNotifications();
      if (!mountedRef.current) return;
      loadedRef.current = true;
      // Keep reads that are still being saved from flickering back to unread.
      const merged = reconcilePending(page.items, pendingReadRef.current);
      setItems(merged.items);
      setCursor(page.nextCursor);
      setUnreadCount(Math.max(0, page.unreadCount - merged.unreadAdjustment));
      setError(null);
    } catch (err) {
      // A silent reload that fails keeps what is already on screen.
      if (mountedRef.current && mode !== 'silent') {
        setError(toApiError(err, 'Could not load your notifications.'));
      }
    } finally {
      if (mountedRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, []);

  const focusReload = useCallback(() => {
    void load(loadedRef.current ? 'silent' : 'initial');
  }, [load]);
  useRefreshOnActive(focusReload);

  const loadMore = useCallback(async () => {
    if (!cursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const page = await fetchNotifications(cursor);
      if (!mountedRef.current) return;
      const merged = reconcilePending(page.items, pendingReadRef.current);
      setItems((current) => appendUnique(current ?? [], merged.items));
      setCursor(page.nextCursor);
      setUnreadCount(Math.max(0, page.unreadCount - merged.unreadAdjustment));
    } catch (err) {
      if (mountedRef.current) setActionError(toApiError(err, 'Could not load more.').message);
    } finally {
      if (mountedRef.current) setIsLoadingMore(false);
    }
  }, [cursor, isLoadingMore]);

  // The decision to call the server uses the list as it is when the user taps (`items` from
  // this render) and the in-flight set; it never depends on a state updater having run.
  const markRead = useCallback(
    async (id: string) => {
      if (!shouldMarkRead(items, id, pendingReadRef.current)) return;
      pendingReadRef.current.add(id);
      setItems((current) => setReadState(current ?? [], id, true));
      setUnreadCount((c) => Math.max(0, c - 1));
      try {
        await markNotificationRead(id);
        pendingReadRef.current.delete(id);
      } catch {
        pendingReadRef.current.delete(id);
        if (!mountedRef.current) return;
        setItems((current) => setReadState(current ?? [], id, false));
        setUnreadCount((c) => c + 1);
        // Resync with the server so the list and badge cannot drift after a failure.
        void load('silent');
      }
    },
    [items, load]
  );

  const markAllRead = useCallback(async () => {
    const before = items;
    const beforeCount = unreadCount;
    setActionError(null);
    setItems((current) => (current ?? []).map((n) => ({ ...n, isRead: true })));
    setUnreadCount(0);
    try {
      await markAllNotificationsRead();
    } catch (err) {
      if (!mountedRef.current) return;
      setItems(before);
      setUnreadCount(beforeCount);
      setActionError(toApiError(err, 'Could not mark all as read.').message);
    }
  }, [items, unreadCount]);

  return {
    items,
    unreadCount,
    isLoading,
    isRefreshing,
    isLoadingMore,
    hasMore: cursor !== null,
    error,
    actionError,
    refresh: () => load('refresh'),
    retry: () => load('initial'),
    loadMore,
    markRead,
    markAllRead,
  };
}
