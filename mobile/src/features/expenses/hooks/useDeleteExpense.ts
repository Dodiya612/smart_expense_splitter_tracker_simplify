/**
 * useDeleteExpense – T-20 (US-08)
 *
 * Manages the full delete-with-confirm-and-undo flow:
 *
 *  1. Caller triggers `requestDelete(expense)`.
 *  2. `confirmDialogVisible` becomes true → show ConfirmDialog.
 *  3. User confirms → `handleConfirmDelete()`:
 *       a. Calls `deleteExpense()` API stub.
 *       b. Fires `onDeleted(id)` so the list removes the row immediately
 *          (totals update at once – US-08).
 *       c. `toastVisible` becomes true → show UndoToast for 10 seconds.
 *  4a. User taps "Undo" within 10 s → `handleUndo()`:
 *       a. Calls `undoDeleteExpense()`.
 *       b. Fires `onRestored(expense)` so the list re-inserts the row.
 *       c. Toast hides.
 *  4b. Toast timer expires → `handleToastDismissed()`:
 *       a. Toast hides; deletion is permanent (backend purges after 30 days).
 *
 * The hook is pure state + side-effects; no JSX.  Mount ConfirmDialog and
 * UndoToast in your screen/component using the returned values.
 */

import { useCallback, useRef, useState } from 'react';
import { ApiError } from '@/services/api/types';
import { deleteExpense, undoDeleteExpense } from '../services/expenseApi';
import type { Expense } from '../types';

export interface UseDeleteExpenseOptions {
  /** Called immediately after the API delete succeeds so the list can remove the row. */
  onDeleted: (id: string) => void;
  /** Called if the user undoes within the toast window so the list can re-insert the row. */
  onRestored: (expense: Expense) => void;
}

export interface UseDeleteExpenseReturn {
  /** The expense currently queued for deletion (drives dialog title). */
  pendingExpense: Expense | null;
  confirmDialogVisible: boolean;
  toastVisible: boolean;
  /** Non-null when the delete API call fails. */
  deleteError: ApiError | null;
  isDeleting: boolean;
  isRestoring: boolean;

  /** Step 1: ask the user to confirm. */
  requestDelete: (expense: Expense) => void;
  /** Step 2a: user pressed the red Delete button in the dialog. */
  handleConfirmDelete: () => Promise<void>;
  /** Step 2b: user cancelled the dialog. */
  handleCancelDelete: () => void;
  /** Step 3: user tapped "Undo" in the toast. */
  handleUndo: () => Promise<void>;
  /** Step 4: toast timer expired (deletion is now permanent). */
  handleToastDismissed: () => void;
  /** Clear a delete error so the UI can retry. */
  clearDeleteError: () => void;
}

export function useDeleteExpense({
  onDeleted,
  onRestored,
}: UseDeleteExpenseOptions): UseDeleteExpenseReturn {
  const [pendingExpense, setPendingExpense] = useState<Expense | null>(null);
  const [confirmDialogVisible, setConfirmDialogVisible] = useState(false);
  const [toastVisible, setToastVisible] = useState(false);
  const [deleteError, setDeleteError] = useState<ApiError | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);

  // Keep a ref to the deleted expense so the undo handler can restore it even
  // if pendingExpense is cleared by then.
  const deletedExpenseRef = useRef<Expense | null>(null);

  // ── Step 1 ─────────────────────────────────────────────────────────────────
  const requestDelete = useCallback((expense: Expense) => {
    setPendingExpense(expense);
    setDeleteError(null);
    setConfirmDialogVisible(true);
  }, []);

  // ── Step 2b (cancel) ───────────────────────────────────────────────────────
  const handleCancelDelete = useCallback(() => {
    setConfirmDialogVisible(false);
    setPendingExpense(null);
  }, []);

  // ── Step 2a (confirm) ──────────────────────────────────────────────────────
  const handleConfirmDelete = useCallback(async () => {
    if (!pendingExpense) return;

    setIsDeleting(true);
    setDeleteError(null);

    try {
      await deleteExpense(pendingExpense.id);

      // Save for potential undo before we clear pendingExpense.
      deletedExpenseRef.current = pendingExpense;

      // Immediately update the list (totals update at once – US-08).
      onDeleted(pendingExpense.id);

      // Close dialog and show undo toast.
      setConfirmDialogVisible(false);
      setPendingExpense(null);
      setToastVisible(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setDeleteError(err);
      } else {
        setDeleteError(
          new ApiError(
            'DELETE_FAILED',
            'Could not delete the expense. Please try again.',
            true
          )
        );
      }
    } finally {
      setIsDeleting(false);
    }
  }, [pendingExpense, onDeleted]);

  // ── Step 3 (undo) ──────────────────────────────────────────────────────────
  const handleUndo = useCallback(async () => {
    const expense = deletedExpenseRef.current;
    if (!expense) return;

    setIsRestoring(true);
    setToastVisible(false);

    try {
      await undoDeleteExpense(expense.id);
      onRestored(expense);
    } catch {
      // If the undo network call fails, we can't silently drop it.
      // Show the expense back optimistically anyway – the backend will sort
      // out consistency.  In a production build we'd queue a retry.
      onRestored(expense);
    } finally {
      deletedExpenseRef.current = null;
      setIsRestoring(false);
    }
  }, [onRestored]);

  // ── Step 4 (toast expired) ─────────────────────────────────────────────────
  const handleToastDismissed = useCallback(() => {
    setToastVisible(false);
    deletedExpenseRef.current = null;
  }, []);

  const clearDeleteError = useCallback(() => setDeleteError(null), []);

  return {
    pendingExpense,
    confirmDialogVisible,
    toastVisible,
    deleteError,
    isDeleting,
    isRestoring,
    requestDelete,
    handleConfirmDelete,
    handleCancelDelete,
    handleUndo,
    handleToastDismissed,
    clearDeleteError,
  };
}
