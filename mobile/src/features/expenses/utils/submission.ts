/**
 * US-34 / T-38 – Save-error handling for the expense form, kept free of React so
 * it can be unit tested (scripts/test-expense-submission.mjs).
 *
 * Rules:
 *  - A retry of the same submission reuses the same Idempotency-Key, so a save
 *    that reached the server before the connection dropped is never stored twice.
 *  - A new submission (the values changed after a failure, or the previous save
 *    succeeded) gets a new key; reusing a key with different values would be
 *    rejected by the server as IDEMPOTENCY_CONFLICT.
 *  - A failed save never changes the form values; it only returns an error.
 */

import { ApiError } from '@/services/api/types';
import type { ExpenseFormValues } from '../types';

export const SAVE_FAILED_MESSAGE =
  'Something went wrong. Your form has been kept – please try again.';

/** Identity of a submission: the values that are actually sent. */
export function submissionSignature(values: ExpenseFormValues): string {
  return JSON.stringify([
    values.amountRaw.trim(),
    values.categoryId,
    values.date,
    values.paymentMode,
    values.notes.trim(),
    values.isRecurring,
    // T-45: the repeat frequency only matters when the repeat is on.
    values.isRecurring ? values.frequency : null,
  ]);
}

export interface SubmissionKeyTracker {
  /** Key for these values: same values → same key (retry), changed values → new key. */
  keyFor: (values: ExpenseFormValues) => string;
  /** Call after a successful save so the next submission starts with a new key. */
  reset: () => void;
}

export function createSubmissionKeyTracker(newKey: () => string): SubmissionKeyTracker {
  let key = newKey();
  let signature: string | null = null;
  return {
    keyFor(values) {
      const next = submissionSignature(values);
      if (signature !== null && signature !== next) {
        key = newKey();
      }
      signature = next;
      return key;
    },
    reset() {
      key = newKey();
      signature = null;
    },
  };
}

export type SubmissionOutcome<T> =
  | { ok: true; saved: T; idempotencyKey: string }
  | { ok: false; error: ApiError; idempotencyKey: string };

/** Turn anything thrown by a save into an ApiError the form can show. */
export function toSaveError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError('UNKNOWN_ERROR', SAVE_FAILED_MESSAGE, true);
}

/**
 * Run one save attempt. The values are only read, never changed, so on failure
 * the form still shows exactly what the user typed.
 */
export async function runSubmission<T>(
  values: ExpenseFormValues,
  tracker: SubmissionKeyTracker,
  save: (values: ExpenseFormValues, idempotencyKey: string) => Promise<T>
): Promise<SubmissionOutcome<T>> {
  const idempotencyKey = tracker.keyFor(values);
  try {
    const saved = await save(values, idempotencyKey);
    return { ok: true, saved, idempotencyKey };
  } catch (err) {
    return { ok: false, error: toSaveError(err), idempotencyKey };
  }
}
