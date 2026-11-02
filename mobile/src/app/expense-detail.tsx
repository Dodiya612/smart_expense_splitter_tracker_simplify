/**
 * Expo Router entry point for Expense Detail View (US-13).
 *
 * Route: /expense-detail
 *
 * Usage:
 *   router.push({
 *     pathname: '/expense-detail',
 *     params: { expense: JSON.stringify(expense) },
 *   });
 */

import React from 'react';
import { useLocalSearchParams } from 'expo-router';
import { ExpenseDetailScreen } from '@/features/expenses/screens/ExpenseDetailScreen';
import type { Expense } from '@/features/expenses/types';

export default function ExpenseDetailRoute() {
  const params = useLocalSearchParams<{ expense?: string }>();

  let expense: Expense | undefined;
  if (params.expense) {
    try {
      expense = JSON.parse(params.expense) as Expense;
    } catch {
      // Handled gracefully by ExpenseDetailScreen safe state
    }
  }

  return <ExpenseDetailScreen expense={expense} />;
}