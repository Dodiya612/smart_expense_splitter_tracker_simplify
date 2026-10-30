/**
 * US-07 / US-09 – Form state and submission logic for add/edit expense.
 *
 * Handles:
 *  - Controlled form state for all fields.
 *  - Shared validation (validateExpenseForm).
 *  - Idempotency key generation so retries never double-save.
 *  - Optimistic-locking conflict detection (US-09).
 *  - `onSuccess` callback receives the saved Expense so the list can update
 *    immediately (instant appearance requirement, US-07).
 */

import { useCallback, useRef, useState } from 'react';
import { ApiError } from '@/services/api/types';
import { createExpense, newIdempotencyKey, updateExpense } from '../services/expenseApi';
import type { Expense, ExpenseFormErrors, ExpenseFormValues, PaymentMode } from '../types';
import { amountToPaise, validateExpenseForm } from '../utils/validation';

export interface UseExpenseFormOptions {
  /** When provided the form operates in edit mode (US-09). */
  existingExpense?: Expense;
  onSuccess: (saved: Expense) => void;
  onCancel: () => void;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function expenseToFormValues(e: Expense): ExpenseFormValues {
  return {
    amountRaw: (e.amountPaise / 100).toFixed(2),
    categoryId: e.categoryId,
    date: e.date,
    paymentMode: e.paymentMode as PaymentMode,
    notes: e.notes,
    isRecurring: e.isRecurring,
  };
}

const EMPTY_FORM: ExpenseFormValues = {
  amountRaw: '',
  categoryId: '',
  date: todayIso(),
  paymentMode: 'upi',
  notes: '',
  isRecurring: false,
};

export interface UseExpenseFormReturn {
  values: ExpenseFormValues;
  fieldErrors: ExpenseFormErrors;
  isLoading: boolean;
  /** Non-field error (network, conflict, etc.) */
  submitError: ApiError | null;
  /** True when the server returned VERSION_CONFLICT */
  hasConflict: boolean;
  isEditMode: boolean;

  handleFieldChange: <K extends keyof ExpenseFormValues>(
    field: K,
    value: ExpenseFormValues[K]
  ) => void;
  handleSubmit: () => Promise<void>;
  handleRetry: () => Promise<void>;
  handleCancel: () => void;
  clearConflict: () => void;
}

export function useExpenseForm({
  existingExpense,
  onSuccess,
  onCancel,
}: UseExpenseFormOptions): UseExpenseFormReturn {
  const isEditMode = Boolean(existingExpense);

  const [values, setValues] = useState<ExpenseFormValues>(
    existingExpense ? expenseToFormValues(existingExpense) : EMPTY_FORM
  );
  const [fieldErrors, setFieldErrors] = useState<ExpenseFormErrors>({});
  const [isLoading, setIsLoading] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [hasConflict, setHasConflict] = useState(false);

  // Keep the idempotency key stable across retries (US-07).
  const idempotencyKeyRef = useRef<string>(newIdempotencyKey());

  const handleFieldChange = useCallback(
    <K extends keyof ExpenseFormValues>(field: K, value: ExpenseFormValues[K]) => {
      setValues((prev) => ({ ...prev, [field]: value }));
      // Clear the field error as soon as the user edits it.
      if (fieldErrors[field]) {
        setFieldErrors((prev) => ({ ...prev, [field]: undefined }));
      }
      // Clear non-field errors when the user makes any change.
      if (submitError) setSubmitError(null);
      if (hasConflict) setHasConflict(false);
    },
    [fieldErrors, submitError, hasConflict]
  );

  const doSubmit = useCallback(
    async (formValues: ExpenseFormValues): Promise<void> => {
      setIsLoading(true);
      setSubmitError(null);

      try {
        const paise = amountToPaise(formValues.amountRaw);
        const base = {
          amountPaise: paise,
          categoryId: formValues.categoryId,
          date: formValues.date,
          paymentMode: formValues.paymentMode,
          notes: formValues.notes.trim(),
          isRecurring: formValues.isRecurring,
          idempotencyKey: idempotencyKeyRef.current,
        };

        let saved: Expense;
        if (isEditMode && existingExpense) {
          saved = await updateExpense(existingExpense.id, {
            ...base,
            version: existingExpense.version,
          });
        } else {
          saved = await createExpense(base);
          // Rotate the key so a second "add" gets a fresh key.
          idempotencyKeyRef.current = newIdempotencyKey();
        }

        onSuccess(saved);
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.code === 'VERSION_CONFLICT') {
            setHasConflict(true);
          } else {
            setSubmitError(err);
          }
        } else {
          setSubmitError(
            new ApiError(
              'UNKNOWN_ERROR',
              'Something went wrong. Your form has been kept – please try again.',
              true
            )
          );
        }
      } finally {
        setIsLoading(false);
      }
    },
    [existingExpense, isEditMode, onSuccess]
  );

  const handleSubmit = useCallback(async () => {
    const errors = validateExpenseForm(values);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});
    await doSubmit(values);
  }, [values, doSubmit]);

  // Retry uses the same idempotency key (US-07: retry never saves twice).
  const handleRetry = useCallback(async () => {
    await doSubmit(values);
  }, [values, doSubmit]);

  const handleCancel = useCallback(() => {
    onCancel();
  }, [onCancel]);

  const clearConflict = useCallback(() => {
    setHasConflict(false);
  }, []);

  return {
    values,
    fieldErrors,
    isLoading,
    submitError,
    hasConflict,
    isEditMode,
    handleFieldChange,
    handleSubmit,
    handleRetry,
    handleCancel,
    clearConflict,
  };
}
