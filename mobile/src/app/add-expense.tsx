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
 * Usage – Review a scanned bill (T-54 / US-16; opened by /scan-bill):
 *   router.replace({ pathname: '/add-expense', params: { draft: encodeDraft(draft) } });
 *
 * On success the saved expense is stringified and passed back via
 * `router.replace` so the calling screen can update its list immediately
 * (instant-appearance requirement, US-07).
 */

import React, { Suspense, lazy } from 'react';
import { Href, router, useLocalSearchParams } from 'expo-router';
import { decodeDraft } from '@/features/bills/utils/billDraft';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';
import { ExpenseFormSkeleton } from '@/features/expenses/components/ExpenseFormSkeleton';
import type { Expense } from '@/features/expenses/types';

const ExpenseFormScreen = lazy(() =>
  import('@/features/expenses/screens/ExpenseFormScreen').then((module) => ({
    default: module.ExpenseFormScreen,
  }))
);

export default function AddExpenseRoute() {
  const params = useLocalSearchParams<{ expense?: string; draft?: string }>();

  let existingExpense: Expense | undefined;
  if (params.expense) {
    try {
      existingExpense = JSON.parse(params.expense) as Expense;
    } catch {
      // Malformed param – open in add mode as a safe fallback.
    }
  }
  // A malformed draft opens the normal empty form.
  const billDraft = existingExpense ? undefined : decodeDraft(params.draft);

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

  function handleScanBill() {
    router.push('/scan-bill' as Href);
  }

  return (
    <RouteErrorBoundary routeName="Add Expense">
      <Suspense fallback={<ExpenseFormSkeleton />}>
        <ExpenseFormScreen
          existingExpense={existingExpense}
          billDraft={billDraft}
          onSuccess={handleSuccess}
          onCancel={handleCancel}
          onScanBill={handleScanBill}
        />
      </Suspense>
    </RouteErrorBoundary>
  );
}
