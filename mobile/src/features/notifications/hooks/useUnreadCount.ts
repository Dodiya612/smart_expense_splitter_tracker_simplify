/**
 * Unread notification count for the Home bell (T-36 / US-38).
 * A failed refresh keeps the last known count: a badge must never raise an error.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchUnreadCount } from '../services/notificationsApi';
import { useRefreshOnActive } from './useRefreshOnActive';

export function useUnreadCount(): { count: number; refresh: () => void } {
  const [count, setCount] = useState(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(() => {
    fetchUnreadCount()
      .then((value) => {
        if (mountedRef.current) setCount(value);
      })
      .catch(() => {
        // Keep the previous count; the notification list shows real errors.
      });
  }, []);

  useRefreshOnActive(refresh);

  return { count, refresh };
}
