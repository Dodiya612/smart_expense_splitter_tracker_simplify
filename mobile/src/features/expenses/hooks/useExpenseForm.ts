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
 *  - T-45 / US-14: with "Repeat this expense" on, the expense is saved and then a
 *    recurring rule is created from the next date. A retry replays both with the
 *    same keys, so neither is ever stored twice.
 */

import { useCallback, useRef, useState } from 'react';
import { ApiError } from '@/services/api/types';
import { createRecurringRule } from '@/features/recurring/services/recurringApi';
import {
  REPEAT_NOT_SET_UP,
  kolkataToday,
  ruleFromExpenseForm,
  ruleIdempotencyKey,
} from '@/features/recurring/utils/recurring';
import { createExpense, newIdempotencyKey, updateExpense } from '../services/expenseApi';
import type { Expense, ExpenseFormErrors, ExpenseFormValues, PaymentMode } from '../types';
import { createSubmissionKeyTracker, runSubmission } from '../utils/submission';
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
    frequency: 'monthly',
  };
}

const EMPTY_FORM: ExpenseFormValues = {
  amountRaw: '',
  categoryId: '',
  date: todayIso(),
  paymentMode: 'upi',
  notes: '',
  isRecurring: false,
  frequency: 'monthly',
};

/** A failed rule create after the expense saved: keep the form and offer Try again. */
function repeatSetupError(err: unknown): ApiError {
  const detail = err instanceof ApiError && err.code !== 'NETWORK_ERROR' ? ` (${err.message})` : '';
  return new ApiError('RECURRING_SETUP_FAILED', `${REPEAT_NOT_SET_UP}${detail}`, true);
}

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

  // Same submission (retry) → same idempotency key; changed values → new key (US-07, US-34).
  const keyTrackerRef = useRef(createSubmissionKeyTracker(newIdempotencyKey));

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

      // Values are only read here: a failed save keeps the form exactly as typed.
      const outcome = await runSubmission(
        formValues,
        keyTrackerRef.current,
        async (submitted, idempotencyKey): Promise<Expense> => {
          const base = {
            amountPaise: amountToPaise(submitted.amountRaw),
            categoryId: submitted.categoryId,
            date: submitted.date,
            paymentMode: submitted.paymentMode,
            notes: submitted.notes.trim(),
            isRecurring: submitted.isRecurring,
            idempotencyKey,
          };
          if (isEditMode && existingExpense) {
            return updateExpense(existingExpense.id, {
              ...base,
              version: existingExpense.version,
            });
          }
          const saved = await createExpense(base);
          if (!submitted.isRecurring) return saved;
          try {
            await createRecurringRule(
              ruleFromExpenseForm(submitted, kolkataToday()),
              ruleIdempotencyKey(idempotencyKey)
            );
          } catch (err) {
            throw repeatSetupError(err);
          }
          return { ...saved, isRecurring: true };
        }
      );
      setIsLoading(false);

      if (outcome.ok) {
        // The next "add" is a new submission with a fresh key.
        if (!isEditMode) keyTrackerRef.current.reset();
        onSuccess(outcome.saved);
      } else if (outcome.error.code === 'VERSION_CONFLICT') {
        setHasConflict(true);
      } else {
        setSubmitError(outcome.error);
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
