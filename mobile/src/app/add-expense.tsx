/**
 * Expo Router entry point for the "add / edit expense" modal.
 *
 * Route:  /add-expense
 * Presentation: modal (configured in _layout.tsx)
 *
 * Usage – Add mode:
 *   router.push('/add-expense');
 *
 * Usage – Edit mode:
 *   router.push({ pathname: '/add-expense', params: { expense: JSON.stringify(expense) } });
 *
 * On success the saved expense is stringified and passed back via
 * `router.replace` so the calling screen can update its list immediately
 * (instant-appearance requirement, US-07).
 */

import React from 'react';
import { router, useLocalSearchParams } from 'expo-router';
import { ExpenseFormScreen } from '@/features/expenses/screens/ExpenseFormScreen';
import type { Expense } from '@/features/expenses/types';

export default function AddExpenseRoute() {
  const params = useLocalSearchParams<{ expense?: string }>();

  let existingExpense: Expense | undefined;
  if (params.expense) {
    try {
      existingExpense = JSON.parse(params.expense) as Expense;
    } catch {
      // Malformed param – open in add mode as a safe fallback.
    }
  }

  function handleSuccess(saved: Expense) {
    // Return the saved expense to the previous screen via a shared param so the
    // list can prepend / update the row without a full refetch.
    router.replace({
      pathname: '/(tabs)/home',
      params: { savedExpense: JSON.stringify(saved) },
    });
  }

  function handleCancel() {
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace('/(tabs)/home');
    }
  }

  return (
    <ExpenseFormScreen
      existingExpense={existingExpense}
      onSuccess={handleSuccess}
      onCancel={handleCancel}
    />
  );
}
