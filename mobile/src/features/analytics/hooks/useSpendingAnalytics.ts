/**
 * useSpendingAnalytics Hook (T-43 / US-12).
 *
 * Manages:
 * - Summary, Trends, Categories data fetching.
 * - Loading, refreshing, error, and retry states.
 * - Granularity (day, week, month) & Date Range preset (1M, 3M, 6M, 1Y, custom).
 * - Spending View Mode (Your Share vs Cash Paid).
 * - Automatic refresh when the screen gains focus or app returns to active (via useRefreshOnActive).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/services/api/types';
import { useRefreshOnActive } from '@/features/notifications/hooks/useRefreshOnActive';
import {
  fetchAnalyticsCategories,
  fetchAnalyticsSummary,
  fetchAnalyticsTrends,
} from '../services/analyticsApi';
import type {
  AnalyticsCategories,
  AnalyticsGranularity,
  AnalyticsRangeParams,
  AnalyticsSummary,
  AnalyticsTrends,
  DateRangePreset,
  SpendingViewMode,
} from '../types';
import { computePresetRange } from '../utils/dateRange';

export interface UseSpendingAnalyticsOptions {
  groupId?: string;
  initialPreset?: DateRangePreset;
  initialGranularity?: AnalyticsGranularity;
  initialMode?: SpendingViewMode;
}

export interface UseSpendingAnalyticsReturn {
  summary: AnalyticsSummary | null;
  trends: AnalyticsTrends | null;
  categories: AnalyticsCategories | null;
  isLoading: boolean;
  isRefreshing: boolean;
  error: ApiError | null;
  viewMode: SpendingViewMode;
  setViewMode: (mode: SpendingViewMode) => void;
  preset: DateRangePreset;
  setPreset: (preset: DateRangePreset) => void;
  granularity: AnalyticsGranularity;
  setGranularity: (granularity: AnalyticsGranularity) => void;
  fromDate: string;
  toDate: string;
  setCustomRange: (from: string, to: string) => void;
  refresh: () => Promise<void>;
  retry: () => Promise<void>;
}

export function useSpendingAnalytics(options: UseSpendingAnalyticsOptions = {}): UseSpendingAnalyticsReturn {
  const {
    groupId,
    initialPreset = '1M',
    initialGranularity = 'day',
    initialMode = 'share',
  } = options;

  const [viewMode, setViewMode] = useState<SpendingViewMode>(initialMode);
  const [preset, setPresetState] = useState<DateRangePreset>(initialPreset);
  const [granularity, setGranularity] = useState<AnalyticsGranularity>(initialGranularity);

  const initialRange = computePresetRange(initialPreset);
  const [fromDate, setFromDate] = useState<string>(initialRange.from);
  const [toDate, setToDate] = useState<string>(initialRange.to);

  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [trends, setTrends] = useState<AnalyticsTrends | null>(null);
  const [categories, setCategories] = useState<AnalyticsCategories | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<ApiError | null>(null);

  const isMountedRef = useRef(true);
  const latestRequestIdRef = useRef(0);
  const hasInitiallyFocusedRef = useRef(false);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const setPreset = useCallback((newPreset: DateRangePreset) => {
    setPresetState(newPreset);
    if (newPreset !== 'custom') {
      const range = computePresetRange(newPreset);
      setFromDate(range.from);
      setToDate(range.to);
      // Auto-adjust default granularity for wider ranges
      if (newPreset === '1Y') {
        setGranularity('month');
      } else if (newPreset === '6M' || newPreset === '3M') {
        setGranularity('week');
      } else {
        setGranularity('day');
      }
    }
  }, []);

  const setCustomRange = useCallback((from: string, to: string) => {
    setPresetState('custom');
    setFromDate(from);
    setToDate(to);
  }, []);

  const loadData = useCallback(
    async (refreshing = false) => {
      const requestId = ++latestRequestIdRef.current;
      if (refreshing) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }
      setError(null);

      const params: AnalyticsRangeParams = {
        from: fromDate,
        to: toDate,
        groupId,
        granularity,
      };

      try {
        const [sumData, trData, catData] = await Promise.all([
          fetchAnalyticsSummary(params),
          fetchAnalyticsTrends(params),
          fetchAnalyticsCategories(params),
        ]);

        if (!isMountedRef.current || requestId !== latestRequestIdRef.current) return;
        setSummary(sumData);
        setTrends(trData);
        setCategories(catData);
        setError(null);
      } catch (err) {
        if (!isMountedRef.current || requestId !== latestRequestIdRef.current) return;
        if (err instanceof ApiError) {
          setError(err);
        } else {
          setError(
            new ApiError('ANALYTICS_FETCH_FAILED', 'Failed to load spending analytics.', true)
          );
        }
      } finally {
        if (isMountedRef.current && requestId === latestRequestIdRef.current) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    },
    [fromDate, toDate, groupId, granularity]
  );

  useEffect(() => {
    void loadData(false);
  }, [loadData]);

  // Screen focus refresh: automatically refetches fresh data when returning to screen after an edit
  useRefreshOnActive(
    useCallback(() => {
      if (!hasInitiallyFocusedRef.current) {
        hasInitiallyFocusedRef.current = true;
        return;
      }
      void loadData(true);
    }, [loadData])
  );

  const refresh = useCallback(async () => {
    await loadData(true);
  }, [loadData]);

  const retry = useCallback(async () => {
    await loadData(false);
  }, [loadData]);

  return {
    summary,
    trends,
    categories,
    isLoading,
    isRefreshing,
    error,
    viewMode,
    setViewMode,
    preset,
    setPreset,
    granularity,
    setGranularity,
    fromDate,
    toDate,
    setCustomRange,
    refresh,
    retry,
  };
}
