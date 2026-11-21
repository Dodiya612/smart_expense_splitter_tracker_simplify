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

import React, { Suspense, lazy } from 'react';
import { useLocalSearchParams } from 'expo-router';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';
import { ExpenseDetailSkeleton } from '@/features/expenses/components/ExpenseDetailSkeleton';
import type { Expense } from '@/features/expenses/types';

const ExpenseDetailScreen = lazy(() =>
  import('@/features/expenses/screens/ExpenseDetailScreen').then((module) => ({
    default: module.ExpenseDetailScreen,
  }))
);

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

  return (
    <RouteErrorBoundary routeName="Expense Detail">
      <Suspense fallback={<ExpenseDetailSkeleton />}>
        <ExpenseDetailScreen expense={expense} />
      </Suspense>
    </RouteErrorBoundary>
  );
}
