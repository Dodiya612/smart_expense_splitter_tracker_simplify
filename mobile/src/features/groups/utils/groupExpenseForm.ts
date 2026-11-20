/**
 * Add group expense form rules (T-31 / US-18, US-19). Pure; unit-tested.
 * Mirrors backend SharedExpenseCreateRequest: amount > 0 paise, description
 * 1–255 chars, category required, notes up to 1000 chars.
 */

import { MAX_AMOUNT_PAISE, parseRupeesToPaise } from '@/utils/money';
import { buildSplitPreview, toSplitWeights, type SplitMode, type SplitPreview } from '@/utils/splits';

export const DESCRIPTION_MAX_LENGTH = 255;
export const NOTES_MAX_LENGTH = 1000;

export interface GroupExpenseFormValues {
  amountText: string;
  description: string;
  categoryId: string | null;
  payerId: string | null;
  notes: string;
  mode: SplitMode;
  /** Participants in the group's member order (the ledger tie order). */
  participantIds: string[];
  /** Typed split values per mode, then per participant. */
  splitValues: Record<SplitMode, Record<string, string>>;
}

export type GroupExpenseFieldErrors = Partial<
  Record<'amountText' | 'description' | 'categoryId' | 'payerId' | 'notes', string>
>;

export function parseTotal(amountText: string): number | null {
  const paise = parseRupeesToPaise(amountText);
  return paise !== null && paise > 0 && paise <= MAX_AMOUNT_PAISE ? paise : null;
}

export function previewFor(values: GroupExpenseFormValues): SplitPreview {
  return buildSplitPreview({
    mode: values.mode,
    totalPaise: parseTotal(values.amountText),
    participantIds: values.participantIds,
    values: values.splitValues[values.mode],
  });
}

export function validateGroupExpense(values: GroupExpenseFormValues): GroupExpenseFieldErrors {
  const errors: GroupExpenseFieldErrors = {};
  const paise = parseRupeesToPaise(values.amountText);
  if (!values.amountText.trim()) errors.amountText = 'Enter the total amount.';
  else if (paise === null) errors.amountText = 'Use a number like 1200 or 1200.50.';
  else if (paise <= 0) errors.amountText = 'The amount must be more than ₹0.';
  else if (paise > MAX_AMOUNT_PAISE) errors.amountText = 'The amount cannot be more than ₹1,00,00,000.';

  const description = values.description.trim();
  if (!description) errors.description = 'Say what this expense was for.';
  else if (description.length > DESCRIPTION_MAX_LENGTH) errors.description = `Keep it under ${DESCRIPTION_MAX_LENGTH} characters.`;

  if (!values.categoryId) errors.categoryId = 'Choose a category.';
  if (!values.payerId) errors.payerId = 'Choose who paid.';
  if (values.notes.length > NOTES_MAX_LENGTH) errors.notes = `Keep notes under ${NOTES_MAX_LENGTH} characters.`;
  return errors;
}

/** True when nothing blocks saving: valid fields and a balanced split. */
export function canSave(values: GroupExpenseFormValues): boolean {
  return Object.keys(validateGroupExpense(values)).length === 0 && previewFor(values).isBalanced;
}

/** Today's date in Asia/Kolkata as YYYY-MM-DD (the app's time zone). */
export function todayInKolkata(now: Date = new Date()): string {
  const ist = new Date(now.getTime() + (330 + now.getTimezoneOffset()) * 60_000);
  const m = String(ist.getMonth() + 1).padStart(2, '0');
  const d = String(ist.getDate()).padStart(2, '0');
  return `${ist.getFullYear()}-${m}-${d}`;
}

/** Request body for POST /api/v1/groups/:groupId/expenses. Call only when canSave() is true. */
export function toCreateBody(values: GroupExpenseFormValues, today: string): Record<string, unknown> {
  const notes = values.notes.trim();
  return {
    amount_paise: parseTotal(values.amountText),
    description: values.description.trim(),
    category_id: values.categoryId,
    expense_date: today,
    paid_by_user_id: values.payerId,
    participant_user_ids: values.participantIds,
    split_mode: values.mode,
    split_weights: toSplitWeights(values.mode, values.participantIds, values.splitValues[values.mode]),
    notes: notes.length > 0 ? notes : undefined,
  };
}

/** Plain messages for the backend's shared expense error codes. */
export function groupExpenseErrorMessage(code: string, fallback: string): string {
  switch (code) {
    case 'INVALID_SPLIT':
    case 'UNBALANCED_SHARES':
      return 'The split does not add up to the total. Check the amounts and try again.';
    case 'PARTICIPANT_NOT_MEMBER':
    case 'PAYER_NOT_MEMBER':
      return 'Someone in this split is no longer in the group. Reload and try again.';
    case 'CATEGORY_NOT_FOUND':
      return 'That category is not available. Pick another one.';
    case 'NOT_FOUND':
      return 'This group no longer exists, or you are not a member.';
    default:
      return fallback;
  }
}
