/**
 * Loads my recurring expenses and runs pause / resume / cancel (T-45 / US-14).
 * Reloads when the screen comes back into focus, so a repeat set up from the
 * add-expense form shows straight away.
 */

import { useCallback, useRef, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import { ApiError } from '@/services/api/types';
import { changeRecurringRule, listRecurringRules } from '../services/recurringApi';
import type { RecurringRule, RuleAction } from '../types';
import { actionDoneText, actionErrorMessage, sortRules } from '../utils/recurring';

export interface UseRecurringRulesReturn {
  rules: RecurringRule[] | null;
  isLoading: boolean;
  isRefreshing: boolean;
  error: ApiError | null;
  /** The rule whose action is in flight, so only its buttons show a spinner. */
  busyRuleId: string | null;
  /** Result of the last action, shown in a banner. */
  actionMessage: { kind: 'success' | 'error'; text: string } | null;
  refresh: () => Promise<void>;
  retry: () => Promise<void>;
  runAction: (rule: RecurringRule, action: RuleAction) => Promise<boolean>;
}

function toApiError(err: unknown, code: string, message: string): ApiError {
  return err instanceof ApiError ? err : new ApiError(code, message, true);
}

export function useRecurringRules(): UseRecurringRulesReturn {
  const [rules, setRules] = useState<RecurringRule[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [busyRuleId, setBusyRuleId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] =
    useState<UseRecurringRulesReturn['actionMessage']>(null);
  const activeRef = useRef(true);
  const hasLoadedRef = useRef(false);

  const load = useCallback(async (mode: 'initial' | 'refresh' | 'silent') => {
    if (mode === 'initial') setIsLoading(true);
    if (mode === 'refresh') {
      setIsRefreshing(true);
      setActionMessage(null);
    }
    setError(null);
    try {
      const data = await listRecurringRules();
      hasLoadedRef.current = true;
      if (activeRef.current) setRules(sortRules(data));
    } catch (err) {
      if (activeRef.current) {
        setError(toApiError(err, 'RECURRING_FETCH_FAILED', 'Could not load your recurring expenses.'));
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

  const runAction = useCallback(async (rule: RecurringRule, action: RuleAction) => {
    setBusyRuleId(rule.id);
    setActionMessage(null);
    try {
      const updated = await changeRecurringRule(rule.id, action);
      if (activeRef.current) {
        setRules((current) =>
          current ? sortRules(current.map((r) => (r.id === updated.id ? updated : r))) : current
        );
        setActionMessage({ kind: 'success', text: actionDoneText(action) });
      }
      return true;
    } catch (err) {
      const apiError = toApiError(err, 'RECURRING_ACTION_FAILED', 'Could not change this repeat. Please try again.');
      if (activeRef.current) {
        setActionMessage({ kind: 'error', text: actionErrorMessage(apiError.code, apiError.message) });
      }
      return false;
    } finally {
      if (activeRef.current) setBusyRuleId(null);
    }
  }, []);

  const refresh = useCallback(() => load('refresh'), [load]);
  const retry = useCallback(() => load('initial'), [load]);

  return { rules, isLoading, isRefreshing, error, busyRuleId, actionMessage, refresh, retry, runAction };
}
