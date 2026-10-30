/**
 * ExpenseListScreen – T-20 host / US-08 / US-13
 *
 * Owns the list of expenses and the full T-20 delete-with-confirm-and-undo
 * flow.  The ConfirmDialog and UndoToast are mounted once here and shared
 * across all list items.
 *
 * Delete flow (US-08):
 *   1. User taps "Delete" on an ExpenseListItem.
 *   2. ConfirmDialog appears.
 *   3. User confirms → expense removed from list immediately (totals update
 *      at once per US-08).  UndoToast appears for 10 seconds.
 *   4a. User taps "Undo" → expense restored.
 *   4b. Toast expires → deletion permanent.
 *
 * Edit flow (US-09):
 *   Tapping "Edit" pushes to the add-expense modal with the expense
 *   serialised as a route param.
 *
 * This screen is intentionally minimal (seed-data only, no real API paging)
 * so Sprint-1 reviewers can see the T-20 flow in isolation. The full paged
 * list (T-21) is Aryan's task.
 */

import React, { useState } from 'react';
import { FlatList, StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { UndoToast } from '@/components/ui/UndoToast';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import { ExpenseListItem } from '../components/ExpenseListItem';
import { useDeleteExpense } from '../hooks/useDeleteExpense';
import type { Expense } from '../types';

// ── Seed data (replaced by real API in T-21) ──────────────────────────────────
const SEED_EXPENSES: Expense[] = [
  {
    id: 'seed-1',
    amountPaise: 34900,
    categoryId: 'food',
    date: new Date().toISOString().slice(0, 10),
    paymentMode: 'upi',
    notes: 'Lunch at office canteen',
    isRecurring: false,
    version: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'seed-2',
    amountPaise: 120000,
    categoryId: 'transport',
    date: new Date().toISOString().slice(0, 10),
    paymentMode: 'card',
    notes: 'Uber to airport',
    isRecurring: false,
    version: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'seed-3',
    amountPaise: 50000,
    categoryId: 'utilities',
    date: new Date().toISOString().slice(0, 10),
    paymentMode: 'net_banking',
    notes: 'Monthly electricity bill',
    isRecurring: true,
    version: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

export function ExpenseListScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const [expenses, setExpenses] = useState<Expense[]>(SEED_EXPENSES);

  // T-20: delete with confirm + 10-second undo toast (US-08)
  const {
    pendingExpense,
    confirmDialogVisible,
    toastVisible,
    deleteError,
    isDeleting,
    requestDelete,
    handleConfirmDelete,
    handleCancelDelete,
    handleUndo,
    handleToastDismissed,
    clearDeleteError,
  } = useDeleteExpense({
    onDeleted: (id) => {
      // Remove from list immediately (totals update at once – US-08).
      setExpenses((prev) => prev.filter((e) => e.id !== id));
    },
    onRestored: (expense) => {
      // Re-insert at original position best effort (simplified: prepend).
      setExpenses((prev) => [expense, ...prev.filter((e) => e.id !== expense.id)]);
    },
  });

  const handleEdit = (expense: Expense) => {
    router.push({
      pathname: '/add-expense' as Href,
      params: { expense: JSON.stringify(expense) },
    });
  };

  const handleAdd = () => {
    router.push('/add-expense' as Href);
  };

  const listHeader = (
    <View style={[styles.header, { paddingBottom: theme.spacing.md }]}>
      <AppText variant="heading" color="textPrimary">
        Expenses
      </AppText>
      <Button
        label="+ Add"
        variant="primary"
        onPress={handleAdd}
        accessibilityLabel="Add a new expense"
      />
    </View>
  );

  const listEmpty = (
    <View style={[styles.empty, { paddingTop: theme.spacing.xxxl }]}>
      <AppText variant="body" color="textSecondary" style={styles.emptyText}>
        No expenses yet. Tap + Add to record your first one.
      </AppText>
    </View>
  );

  return (
    <View
      style={[styles.root, { backgroundColor: theme.colors.background }]}
    >
      {/* ── Delete error banner ──────────────────────────────────── */}
      {deleteError && (
        <View
          accessibilityRole="alert"
          accessibilityLiveRegion="assertive"
          style={[
            styles.errorBanner,
            {
              backgroundColor: theme.colors.negative.soft,
              borderColor: theme.colors.negative.text,
              borderRadius: theme.radii.md,
              padding: theme.spacing.md,
              margin: theme.spacing.lg,
              gap: theme.spacing.sm,
            },
          ]}
        >
          <AppText variant="small" color="negative">
            {`[!] ${deleteError.message}`}
          </AppText>
          <Button
            label="Dismiss"
            variant="outline"
            onPress={clearDeleteError}
            accessibilityLabel="Dismiss error"
          />
        </View>
      )}

      {/* ── Expense list ─────────────────────────────────────────── */}
      <FlatList
        data={expenses}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <ExpenseListItem
            expense={item}
            onEdit={handleEdit}
            onDelete={requestDelete}
          />
        )}
        ListHeaderComponent={listHeader}
        ListEmptyComponent={listEmpty}
        contentContainerStyle={[
          styles.listContent,
          {
            paddingHorizontal: theme.spacing.lg,
            paddingTop: insets.top + theme.spacing.md,
            paddingBottom: insets.bottom + theme.spacing.xxxl,
            gap: theme.spacing.md,
          },
        ]}
        showsVerticalScrollIndicator={false}
        accessibilityRole="list"
        accessibilityLabel="Expense list"
      />

      {/* ── T-20: Confirm delete dialog (US-08) ─────────────────── */}
      <ConfirmDialog
        visible={confirmDialogVisible}
        title="Delete expense?"
        message={
          pendingExpense
            ? `Delete ₹${(pendingExpense.amountPaise / 100).toFixed(2)} on ${pendingExpense.date}? You'll have 10 seconds to undo.`
            : 'Are you sure you want to delete this expense?'
        }
        confirmLabel="Delete"
        cancelLabel="Keep it"
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        isLoading={isDeleting}
      />

      {/* ── T-20: 10-second undo toast (US-08) ──────────────────── */}
      <UndoToast
        visible={toastVisible}
        message="Expense deleted"
        durationMs={10_000}
        onUndo={handleUndo}
        onDismissed={handleToastDismissed}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  listContent: {
    flexGrow: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  empty: {
    alignItems: 'center',
  },
  emptyText: {
    textAlign: 'center',
    maxWidth: 280,
  },
  errorBanner: {
    borderWidth: 1,
  },
});
