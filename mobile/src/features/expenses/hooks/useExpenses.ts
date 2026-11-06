/**
 * useExpenses – T-21 / S1-FE-04 (US-13 & US-09)
 *
 * Reusable data hook for fetching paginated expense lists with:
 *   - Initial loading state (isLoading)
 *   - Pull-to-refresh (isRefreshing, refresh)
 *   - Infinite scroll / offset-based pagination (hasMore, loadMore, isLoadingMore)
 *   - Duplicate request & race condition prevention (inFlightRef, requestIdRef)
 *   - Id-based deduplication of appended pages
 *   - Error handling & retry mechanism (error, retry)
 *   - No fallback to seed/mock data (real API data only)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/services/api/types';
import { fetchExpenses, type FetchExpensesParams } from '../services/expenseApi';
import type { Expense } from '../types';

export interface UseExpensesOptions {
  /** Number of items to fetch per page (default: 20). */
  limit?: number;
  /** Optional filter by category ID */
  categoryId?: string;
  /** Optional filter expenses on or after this date (YYYY-MM-DD) */
  from?: string;
  /** Optional filter expenses on or before this date (YYYY-MM-DD) */
  to?: string;
  /** Optional search text in description or merchant */
  query?: string;
  /** Whether to automatically fetch on mount or parameter change (default: true). */
  minAmount?: number;
  maxAmount?: number;
  paymentMode?: string;
  autoFetch?: boolean;
}

export interface UseExpensesReturn {
  expenses: Expense[];
  isLoading: boolean;
  isRefreshing: boolean;
  isLoadingMore: boolean;
  error: ApiError | null;
  hasMore: boolean;
  total: number;
  loadMore: () => Promise<void>;
  refresh: () => Promise<void>;
  retry: () => Promise<void>;
}

export function useExpenses({
  limit = 20,
  categoryId,
  from,
  to,
  query,
  minAmount,
  maxAmount,
  paymentMode,
  autoFetch = true,
}: UseExpensesOptions = {}): UseExpensesReturn {
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(autoFetch);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [isLoadingMore, setIsLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [hasMore, setHasMore] = useState<boolean>(false);
  const [total, setTotal] = useState<number>(0);

  // Synchronization and pagination state refs
  const offsetRef = useRef<number>(0);
  const inFlightRef = useRef<boolean>(false);
  const requestIdRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);
  const hasMoreRef = useRef<boolean>(false);
  const totalRef = useRef<number>(0);

  // Cache filter options in a ref so callbacks read latest options without identity changes
  const filterParamsRef = useRef<FetchExpensesParams>({
    limit,
    categoryId,
    from,
    to,
    query,
    minAmount,
    maxAmount,
    paymentMode,
  });

    useEffect(() => {
    filterParamsRef.current = {
      limit,
      categoryId,
      from,
      to,
      query,
      minAmount,
      maxAmount,
      paymentMode,
    };
  }, [limit, categoryId, from, to, query, minAmount, maxAmount, paymentMode]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  /**
   * Internal worker function to execute page requests with strict sequencing.
   * Uses refs for pagination state (hasMoreRef, offsetRef) to maintain a stable identity.
   */
  const executeFetch = useCallback(
    async ({
      isRefresh = false,
      isNextPage = false,
    }: {
      isRefresh?: boolean;
      isNextPage?: boolean;
    } = {}) => {
      // Prevent duplicate simultaneous requests
      if (inFlightRef.current) {
        return;
      }

      // If requesting next page, verify there is more data to load via stable ref
      if (isNextPage && !hasMoreRef.current) {
        return;
      }

      inFlightRef.current = true;
      const currentRequestId = ++requestIdRef.current;

      const targetOffset = isRefresh || !isNextPage ? 0 : offsetRef.current;
      const targetLimit = filterParamsRef.current.limit ?? 20;

      if (isRefresh) {
        setIsRefreshing(true);
        setError(null);
      } else if (isNextPage) {
        setIsLoadingMore(true);
      } else {
        setIsLoading(true);
        setError(null);
      }

      try {
        const result = await fetchExpenses({
          limit: targetLimit,
          offset: targetOffset,
          categoryId: filterParamsRef.current.categoryId,
          from: filterParamsRef.current.from,
          to: filterParamsRef.current.to,
          query: filterParamsRef.current.query,
          minAmount: filterParamsRef.current.minAmount,
          maxAmount: filterParamsRef.current.maxAmount,
          paymentMode: filterParamsRef.current.paymentMode,
        });

        // Guard against stale requests and unmounted components
        if (!isMountedRef.current || currentRequestId !== requestIdRef.current) {
          return;
        }

        if (isRefresh || !isNextPage) {
          setExpenses(result.expenses);
          offsetRef.current = result.expenses.length;
        } else {
            setExpenses((prev: Expense[]) => {
            const existingIds = new Set(prev.map((e) => e.id));
            const uniqueIncoming = result.expenses.filter((e) => !existingIds.has(e.id));
            return [...prev, ...uniqueIncoming];
          });
          offsetRef.current += result.expenses.length;
        }

        totalRef.current = result.total;
        setTotal(result.total);

        hasMoreRef.current = result.hasMore;
        setHasMore(result.hasMore);

        setError(null);
      } catch (err: unknown) {
        if (!isMountedRef.current || currentRequestId !== requestIdRef.current) {
          return;
        }

        const apiErr =
          err instanceof ApiError
            ? err
            : new ApiError(
                'FETCH_FAILED',
                err instanceof Error ? err.message : 'Unable to fetch expenses. Please try again.',
                true
              );

        setError(apiErr);
      } finally {
        if (isMountedRef.current && currentRequestId === requestIdRef.current) {
          inFlightRef.current = false;
          setIsLoading(false);
          setIsRefreshing(false);
          setIsLoadingMore(false);
        }
      }
    },
    [] // Stable dependencies: all dynamic state read through refs or stable setters
  );

  /**
   * Refreshes the list from the first page (offset = 0).
   */
  const refresh = useCallback(async () => {
    await executeFetch({ isRefresh: true });
  }, [executeFetch]);

  /**
   * Loads the next page of expenses and appends them to the current list.
   */
  const loadMore = useCallback(async () => {
    await executeFetch({ isNextPage: true });
  }, [executeFetch]);

  /**
   * Retries fetching data after an error occurs.
   */
  const retry = useCallback(async () => {
    await executeFetch({ isRefresh: false, isNextPage: false });
  }, [executeFetch]);

  // Initial fetch and fetch on filter parameter changes
  useEffect(() => {
    if (autoFetch) {
      void (async () => {
        await executeFetch({ isRefresh: false, isNextPage: false });
      })();
    }
  }, [limit, categoryId, from, to, query, minAmount, maxAmount, paymentMode, autoFetch, executeFetch]);

  return {
    expenses,
    isLoading,
    isRefreshing,
    isLoadingMore,
    error,
    hasMore,
    total,
    loadMore,
    refresh,
    retry,
  };
}
