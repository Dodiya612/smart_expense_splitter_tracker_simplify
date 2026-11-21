/**
 * useBudgets Custom Hook (T-49 / US-25).
 *
 * Encapsulates state machine:
 * - list of budgets
 * - loading, refreshing, error states with retry
 * - create, update, delete actions
 * - race-condition protection via latestRequestIdRef
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { budgetsApi } from '../services/budgetsApi';
import type { Budget, BudgetCreatePayload, BudgetUpdatePayload } from '../types';

export function useBudgets() {
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const latestRequestIdRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const fetchBudgets = useCallback(async (isRefresh = false) => {
    const requestId = ++latestRequestIdRef.current;
    if (isRefresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    try {
      const res = await budgetsApi.listBudgets();
      if (!isMountedRef.current || requestId !== latestRequestIdRef.current) return;
      setBudgets(res.budgets);
      setTotal(res.total);
    } catch (err: any) {
      if (!isMountedRef.current || requestId !== latestRequestIdRef.current) return;
      setError(err?.message || 'Failed to load budgets. Please try again.');
    } finally {
      if (isMountedRef.current && requestId === latestRequestIdRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchBudgets();
  }, [fetchBudgets]);

  const handleCreate = useCallback(
    async (payload: BudgetCreatePayload) => {
      setIsSubmitting(true);
      try {
        // Generate an idempotency key to prevent double submissions
        const idempotencyKey = `budget-create-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
        const created = await budgetsApi.createBudget(payload, idempotencyKey);
        setBudgets((prev) => [created, ...prev]);
        setTotal((prev) => prev + 1);
        return created;
      } finally {
        if (isMountedRef.current) {
          setIsSubmitting(false);
        }
      }
    },
    []
  );

  const handleUpdate = useCallback(
    async (budgetId: string, payload: BudgetUpdatePayload) => {
      setIsSubmitting(true);
      try {
        const updated = await budgetsApi.updateBudget(budgetId, payload);
        setBudgets((prev) => prev.map((b) => (b.id === budgetId ? updated : b)));
        return updated;
      } finally {
        if (isMountedRef.current) {
          setIsSubmitting(false);
        }
      }
    },
    []
  );

  const handleDelete = useCallback(
    async (budgetId: string) => {
      setIsSubmitting(true);
      try {
        await budgetsApi.deleteBudget(budgetId);
        setBudgets((prev) => prev.filter((b) => b.id !== budgetId));
        setTotal((prev) => Math.max(0, prev - 1));
      } finally {
        if (isMountedRef.current) {
          setIsSubmitting(false);
        }
      }
    },
    []
  );

  return {
    budgets,
    total,
    isLoading,
    isRefreshing,
    isSubmitting,
    error,
    refresh: () => fetchBudgets(true),
    retry: () => fetchBudgets(false),
    createBudget: handleCreate,
    updateBudget: handleUpdate,
    deleteBudget: handleDelete,
  };
}
