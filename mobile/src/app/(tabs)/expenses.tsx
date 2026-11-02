/**
 * Expenses tab – hosts the ExpenseHistoryScreen (US-13).
 *
 * Provides paginated transaction history, pull-to-refresh, filters,
 * detail navigation, and T-20 delete/undo integration.
 */

import React from 'react';
import { ExpenseHistoryScreen } from '@/features/expenses/screens/ExpenseHistoryScreen';

export default function ExpensesTab() {
  return <ExpenseHistoryScreen />;
}
