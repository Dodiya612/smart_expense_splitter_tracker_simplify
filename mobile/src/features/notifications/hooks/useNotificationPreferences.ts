/**
 * Per-type notification settings (T-36 / US-38). Toggling is optimistic and rolled
 * back, with a message, if the server rejects it.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/services/api/types';
import { fetchPreferences, savePreference } from '../services/notificationsApi';
import type { NotificationPreference } from '../types';
import { useRefreshOnActive } from './useRefreshOnActive';

export interface UseNotificationPreferencesReturn {
  preferences: NotificationPreference[] | null;
  isLoading: boolean;
  error: ApiError | null;
  actionError: string | null;
  retry: () => Promise<void>;
  setEnabled: (kind: string, enabled: boolean) => Promise<void>;
}

export function useNotificationPreferences(): UseNotificationPreferencesReturn {
  const [preferences, setPreferences] = useState<NotificationPreference[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  // Fetches and stores the result. Callers set the loading state first, so the first
  // load (isLoading starts true) never sets state synchronously inside an effect.
  const fetchAndStore = useCallback(async () => {
    try {
      const data = await fetchPreferences();
      if (mountedRef.current) {
        setPreferences(data);
        setError(null);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(
          err instanceof ApiError
            ? err
            : new ApiError('PREFERENCES_FAILED', 'Could not load your settings.', true)
        );
      }
    } finally {
      if (mountedRef.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Loads on focus (and when the app returns to the foreground), like the other hooks.
  const reload = useCallback(() => {
    void fetchAndStore();
  }, [fetchAndStore]);
  useRefreshOnActive(reload);

  const retry = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    await fetchAndStore();
  }, [fetchAndStore]);

  const setEnabled = useCallback(async (kind: string, enabled: boolean) => {
    setActionError(null);
    const apply = (value: boolean) =>
      setPreferences((current) =>
        (current ?? []).map((p) => (p.kind === kind ? { ...p, enabled: value } : p))
      );
    apply(enabled);
    try {
      const saved = await savePreference(kind, enabled);
      if (mountedRef.current && saved.length > 0) setPreferences(saved);
    } catch (err) {
      if (!mountedRef.current) return;
      apply(!enabled);
      setActionError(
        err instanceof ApiError ? err.message : 'Could not save that change. Try again.'
      );
    }
  }, []);

  return { preferences, isLoading, error, actionError, retry, setEnabled };
}
