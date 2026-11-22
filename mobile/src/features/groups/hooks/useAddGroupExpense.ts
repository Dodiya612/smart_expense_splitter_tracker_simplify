/**
 * Add group expense form state, live split preview and save (T-31 / US-18, US-19).
 * Save is refused unless the split is balanced; one idempotency key per form so
 * a retried save can't create a duplicate.
 */

import { useCallback, useMemo, useRef, useState } from 'react';
import { newIdempotencyKey } from '@/features/expenses/services/expenseApi';
import type { SplitMode } from '@/utils/splits';
import { createGroupExpense, type SavedGroupExpense } from '../services/groupExpenseApi';
import {
  groupExpenseErrorMessage,
  previewFor,
  toCreateBody,
  todayInKolkata,
  validateGroupExpense,
  type GroupExpenseFieldErrors,
  type GroupExpenseFormValues,
} from '../utils/groupExpenseForm';
import { toApiError } from './useGroups';

type TextField = 'amountText' | 'description' | 'notes';

export function useAddGroupExpense(groupId: string, memberIds: string[], currentUserId?: string) {
  const [values, setValues] = useState<GroupExpenseFormValues>(() => ({
    amountText: '',
    description: '',
    categoryId: null,
    payerId: currentUserId && memberIds.includes(currentUserId) ? currentUserId : memberIds[0] ?? null,
    notes: '',
    mode: 'equal',
    participantIds: [...memberIds],
    splitValues: { equal: {}, exact: {}, percentage: {}, parts: {} },
  }));
  const [fieldErrors, setFieldErrors] = useState<GroupExpenseFieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const idempotencyKey = useRef(newIdempotencyKey());

  const preview = useMemo(() => previewFor(values), [values]);

  const patch = useCallback((next: Partial<GroupExpenseFormValues>, clear?: keyof GroupExpenseFieldErrors) => {
    setValues((prev) => ({ ...prev, ...next }));
    if (clear) setFieldErrors((prev) => ({ ...prev, [clear]: undefined }));
    setSubmitError(null);
  }, []);

  const setText = useCallback((field: TextField, text: string) => patch({ [field]: text }, field), [patch]);

  const toggleParticipant = useCallback((userId: string) => {
    setValues((prev) => {
      const included = new Set(prev.participantIds);
      if (included.has(userId)) included.delete(userId);
      else included.add(userId);
      // Keep the group's member order: it is the ledger's tie-break order.
      return { ...prev, participantIds: memberIds.filter((id) => included.has(id)) };
    });
    setSubmitError(null);
  }, [memberIds]);

  const setSplitValue = useCallback((userId: string, text: string) => {
    setValues((prev) => ({
      ...prev,
      splitValues: { ...prev.splitValues, [prev.mode]: { ...prev.splitValues[prev.mode], [userId]: text } },
    }));
    setSubmitError(null);
  }, []);

  const save = useCallback(async (): Promise<SavedGroupExpense | null> => {
    if (isSaving) return null;
    const errors = validateGroupExpense(values);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return null;
    if (!previewFor(values).isBalanced) {
      setSubmitError(previewFor(values).problem ?? 'The split does not add up yet.');
      return null;
    }
    setIsSaving(true);
    setSubmitError(null);
    try {
      return await createGroupExpense(groupId, toCreateBody(values, todayInKolkata()), idempotencyKey.current);
    } catch (err) {
      const apiError = toApiError(err, 'GROUP_EXPENSE_FAILED', 'Could not save the expense. Please try again.');
      setSubmitError(groupExpenseErrorMessage(apiError.code, apiError.message));
      return null;
    } finally {
      setIsSaving(false);
    }
  }, [groupId, isSaving, values]);

  return {
    values,
    preview,
    fieldErrors,
    submitError,
    isSaving,
    setText,
    setCategory: (id: string) => patch({ categoryId: id }, 'categoryId'),
    setPayer: (id: string) => patch({ payerId: id }, 'payerId'),
    setMode: (mode: SplitMode) => patch({ mode }),
    toggleParticipant,
    setSplitValue,
    save,
  };
}

export type UseAddGroupExpenseReturn = ReturnType<typeof useAddGroupExpense>;
