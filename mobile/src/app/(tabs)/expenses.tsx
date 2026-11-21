/**
 * Expenses tab – hosts the ExpenseHistoryScreen (US-13).
 *
 * Provides paginated transaction history, pull-to-refresh, filters,
 * detail navigation, and T-20 delete/undo integration.
 */

import React, { Suspense, lazy } from 'react';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';
import { ExpenseHistorySkeleton } from '@/features/expenses/components/ExpenseHistorySkeleton';

const ExpenseHistoryScreen = lazy(() =>
  import('@/features/expenses/screens/ExpenseHistoryScreen').then((module) => ({
    default: module.ExpenseHistoryScreen,
  }))
);

export default function ExpensesTab() {
  return (
    <RouteErrorBoundary routeName="Expenses">
      <Suspense fallback={<ExpenseHistorySkeleton />}>
        <ExpenseHistoryScreen />
      </Suspense>
    </RouteErrorBoundary>
  );
}
