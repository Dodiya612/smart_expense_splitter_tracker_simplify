/**
 * Settle-sheet rules (T-33 / US-10, failure handling per US-34), free of React.
 *
 * Idempotency-Key rule (same as the expense form):
 *  - Retry of the same submission reuses the same key, so a settlement that
 *    reached the server before the connection dropped is never stored twice.
 *  - A changed submission, or the next one after a success, gets a new key;
 *    reusing a key with a different body is rejected as IDEMPOTENCY_CONFLICT.
 * A failed save never changes the sheet's values; it only returns an error.
 */

import { ApiError } from '@/services/api/types';
import { formatPaise, parseRupeesToPaise } from '@/utils/money';
import type { SettlementCreatePayload } from '../types';

export const SETTLE_FAILED_MESSAGE =
  'Could not record the settlement. Your details are kept – please try again.';

/** Identity of a submission: exactly what is sent. */
export function settlementSignature(payload: SettlementCreatePayload): string {
  return JSON.stringify([
    payload.payerId,
    payload.payeeId,
    payload.amountPaise ?? null,
    payload.isFullSettlement,
    payload.paymentMethod ?? null,
    payload.notes?.trim() || null,
    payload.settlementDate ?? null,
  ]);
}

export interface SettlementKeyTracker {
  keyFor: (payload: SettlementCreatePayload) => string;
  /** Call after a successful save so the next settlement starts with a new key. */
  reset: () => void;
}

export function createSettlementKeyTracker(newKey: () => string): SettlementKeyTracker {
  let key = newKey();
  let signature: string | null = null;
  return {
    keyFor(payload) {
      const next = settlementSignature(payload);
      if (signature !== null && signature !== next) key = newKey();
      signature = next;
      return key;
    },
    reset() {
      key = newKey();
      signature = null;
    },
  };
}

export type SettleOutcome<T> =
  | { ok: true; saved: T; idempotencyKey: string }
  | { ok: false; error: ApiError; idempotencyKey: string };

export function toSettleError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError('SETTLEMENT_FAILED', SETTLE_FAILED_MESSAGE, true);
}

/** One save attempt. The payload is only read, so the sheet keeps its values on failure. */
export async function runSettlement<T>(
  payload: SettlementCreatePayload,
  tracker: SettlementKeyTracker,
  save: (payload: SettlementCreatePayload, idempotencyKey: string) => Promise<T>
): Promise<SettleOutcome<T>> {
  const idempotencyKey = tracker.keyFor(payload);
  try {
    return { ok: true, saved: await save(payload, idempotencyKey), idempotencyKey };
  } catch (err) {
    return { ok: false, error: toSettleError(err), idempotencyKey };
  }
}

export type AmountCheck = { ok: true; amountPaise: number } | { ok: false; message: string };

/** Typed rupees → paise, between ₹0.01 and what is outstanding. The server checks again. */
export function checkSettlementAmount(raw: string, outstandingPaise: number): AmountCheck {
  const amountPaise = parseRupeesToPaise(raw);
  if (amountPaise === null || amountPaise <= 0) {
    return { ok: false, message: 'Enter an amount greater than ₹0, with at most 2 decimals.' };
  }
  if (amountPaise > outstandingPaise) {
    return { ok: false, message: `The amount cannot be more than ${formatPaise(outstandingPaise)}, which is what is owed.` };
  }
  return { ok: true, amountPaise };
}

/** Builds the request. Full settlement sends the exact outstanding amount too, so a stale screen gets AMOUNT_MISMATCH. */
export function buildSettlementPayload(input: {
  payerId: string;
  payeeId: string;
  amountPaise: number;
  outstandingPaise: number;
  paymentMethod: string;
  notes: string;
}): SettlementCreatePayload {
  const notes = input.notes.trim();
  return {
    payerId: input.payerId,
    payeeId: input.payeeId,
    amountPaise: input.amountPaise,
    isFullSettlement: input.amountPaise === input.outstandingPaise,
    paymentMethod: input.paymentMethod,
    ...(notes ? { notes } : {}),
  };
}
