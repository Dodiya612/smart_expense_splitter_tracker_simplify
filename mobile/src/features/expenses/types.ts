/**
 * US-07 / US-09  –  Expense form types.
 *
 * Amounts are stored as integer paise (1 INR = 100 paise).
 * The form keeps the raw string the user typed so validation can report
 * friendly errors; conversion to paise happens only on submit.
 *
 * `version` is required when editing so the backend can detect concurrent
 * edits (US-09 optimistic-locking requirement).
 */

export type PaymentMode =
  | 'upi'
  | 'card'
  | 'cash'
  | 'net_banking'
  | 'wallet'
  | 'other';

export const PAYMENT_MODE_LABELS: Record<PaymentMode, string> = {
  upi: 'UPI',
  card: 'Card',
  cash: 'Cash',
  net_banking: 'Net Banking',
  wallet: 'Wallet',
  other: 'Other',
};

export const PAYMENT_MODES: PaymentMode[] = [
  'upi',
  'card',
  'cash',
  'net_banking',
  'wallet',
  'other',
];

// ── Category ─────────────────────────────────────────────────────────────────
// Provisional list; the backend / ML team will confirm ids.
export interface Category {
  id: string;
  label: string;
  /** Index into theme.categoryPalette */
  paletteIndex: number;
}

export const CATEGORIES: Category[] = [
  { id: 'food', label: 'Food & Drink', paletteIndex: 0 },
  { id: 'transport', label: 'Transport', paletteIndex: 1 },
  { id: 'groceries', label: 'Groceries', paletteIndex: 2 },
  { id: 'health', label: 'Health', paletteIndex: 3 },
  { id: 'entertainment', label: 'Entertainment', paletteIndex: 4 },
  { id: 'utilities', label: 'Utilities', paletteIndex: 5 },
  { id: 'shopping', label: 'Shopping', paletteIndex: 6 },
  { id: 'travel', label: 'Travel', paletteIndex: 7 },
  { id: 'other', label: 'Other', paletteIndex: 8 },
];

// ── Form values ───────────────────────────────────────────────────────────────
/**
 * Raw form state – all fields are strings so controlled TextInputs stay simple.
 * `amountRaw` is what the user types (e.g. "1234.50"); conversion to paise
 * happens in validation.
 */
export interface ExpenseFormValues {
  amountRaw: string;
  categoryId: string;
  date: string;           // ISO date string  "YYYY-MM-DD"
  paymentMode: PaymentMode;
  notes: string;
  /** Set to 'true' string when the recurring toggle is on */
  isRecurring: boolean;
}

export type ExpenseFormErrors = {
  [K in keyof ExpenseFormValues]?: string;
};

// ── Domain model (returned from / sent to the API) ────────────────────────────
export interface Expense {
  id: string;
  amountPaise: number;
  categoryId: string;
  date: string;
  paymentMode: PaymentMode;
  notes: string;
  isRecurring: boolean;
  /** Optimistic-locking version field (US-09) */
  version: number;
  createdAt: string;
  updatedAt: string;
}

// ── Submit payload ────────────────────────────────────────────────────────────
export interface CreateExpensePayload {
  amountPaise: number;
  categoryId: string;
  date: string;
  paymentMode: PaymentMode;
  notes: string;
  isRecurring: boolean;
  idempotencyKey: string;
}

export interface UpdateExpensePayload extends CreateExpensePayload {
  version: number;
}

// ── T-23b: AI Category Suggestion (US-26) ────────────────────────────────────

export interface SuggestionResponse {
  categoryId: string;
  /** 0–1 confidence score from the classifier */
  confidence: number;
  /** Which pipeline layer answered: user-history | classifier | llm */
  source: 'history' | 'classifier' | 'llm';
}

export interface SuggestionFeedback {
  /** The description that triggered the suggestion */
  description: string;
  /** The categoryId the model suggested */
  suggestedCategoryId: string;
  /** The categoryId the user actually chose (may differ) */
  chosenCategoryId: string;
  /** Whether the user accepted the suggestion without changing it */
  accepted: boolean;
}
