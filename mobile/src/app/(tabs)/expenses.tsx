/**
 * Expenses tab – hosts the ExpenseListScreen (T-20, US-08 / US-13).
 *
 * The list screen itself owns the ConfirmDialog and UndoToast so one
 * instance is shared across all items.
 */

import React from 'react';
import { ExpenseListScreen } from '@/features/expenses/screens/ExpenseListScreen';

export default function ExpensesTab() {
  return <ExpenseListScreen />;
}
