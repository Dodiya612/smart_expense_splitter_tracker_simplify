/**
 * Loads the current user's groups (T-29 / US-17).
 * Reloads whenever the Groups tab comes back into focus, so a group that was
 * just created or joined shows up without a manual refresh.
 */

import { useCallback, useRef, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import { ApiError } from '@/services/api/types';
import { listGroups } from '../services/groupsApi';
import type { GroupSummary } from '../types';

export interface UseGroupsReturn {
  groups: GroupSummary[] | null;
  isLoading: boolean;
  isRefreshing: boolean;
  error: ApiError | null;
  refresh: () => Promise<void>;
  retry: () => Promise<void>;
}

export function toApiError(err: unknown, code: string, message: string): ApiError {
  return err instanceof ApiError ? err : new ApiError(code, message, true);
}

export function useGroups(): UseGroupsReturn {
  const [groups, setGroups] = useState<GroupSummary[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const activeRef = useRef(true);
  const hasLoadedRef = useRef(false);

  const load = useCallback(async (mode: 'initial' | 'refresh' | 'silent') => {
    if (mode === 'initial') setIsLoading(true);
    if (mode === 'refresh') setIsRefreshing(true);
    setError(null);
    try {
      const data = await listGroups();
      hasLoadedRef.current = true;
      if (activeRef.current) setGroups(data);
    } catch (err) {
      if (activeRef.current) {
        setError(toApiError(err, 'GROUPS_FETCH_FAILED', 'Could not load your groups.'));
      }
    } finally {
      if (activeRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      activeRef.current = true;
      void load(hasLoadedRef.current ? 'silent' : 'initial');
      return () => {
        activeRef.current = false;
      };
    }, [load])
  );

  const refresh = useCallback(() => load('refresh'), [load]);
  const retry = useCallback(() => load('initial'), [load]);

  return { groups, isLoading, isRefreshing, error, refresh, retry };
}
