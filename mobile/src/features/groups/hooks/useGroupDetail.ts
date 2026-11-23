/**
 * Loads one group's details and active members (T-29 / US-17).
 * A stranger gets 404 from the backend; that is shown as "group not found".
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/services/api/types';
import { getGroup } from '../services/groupsApi';
import type { GroupDetail } from '../types';
import { toApiError } from './useGroups';

export interface UseGroupDetailReturn {
  group: GroupDetail | null;
  isLoading: boolean;
  isRefreshing: boolean;
  error: ApiError | null;
  refresh: () => Promise<void>;
  retry: () => Promise<void>;
}

const MISSING_ID_ERROR = new ApiError('NOT_FOUND', 'This group could not be found.', false);

type FetchResult = { data: GroupDetail } | { error: ApiError };

export function useGroupDetail(groupId: string | undefined): UseGroupDetailReturn {
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  /** Fetches without touching state, so it is safe to start from an effect. */
  const fetchGroup = useCallback(async (id: string): Promise<FetchResult> => {
    try {
      return { data: await getGroup(id) };
    } catch (err) {
      return { error: toApiError(err, 'GROUP_FETCH_FAILED', 'Could not load this group.') };
    }
  }, []);

  const applyResult = useCallback((result: FetchResult) => {
    if (!mountedRef.current) return;
    if ('data' in result) {
      setGroup(result.data);
      setError(null);
    } else {
      setError(result.error);
    }
    setIsLoading(false);
    setIsRefreshing(false);
  }, []);

  useEffect(() => {
    if (!groupId) return;
    void fetchGroup(groupId).then(applyResult);
  }, [groupId, fetchGroup, applyResult]);

  const refresh = useCallback(async () => {
    if (!groupId) return;
    setIsRefreshing(true);
    applyResult(await fetchGroup(groupId));
  }, [groupId, fetchGroup, applyResult]);

  const retry = useCallback(async () => {
    if (!groupId) return;
    setIsLoading(true);
    setError(null);
    applyResult(await fetchGroup(groupId));
  }, [groupId, fetchGroup, applyResult]);

  if (!groupId) {
    return { group: null, isLoading: false, isRefreshing: false, error: MISSING_ID_ERROR, refresh, retry };
  }

  return { group, isLoading, isRefreshing, error, refresh, retry };
}
