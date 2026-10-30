/**
 * US-07 / US-09 – Shared validation for add and edit expense forms.
 *
 * Rules:
 *  - Amount: required; at most 2 decimal places; > 0; ≤ ₹1 crore (10_000_000).
 *  - Category: required (must be one of the known ids).
 *  - Date: required; must be a valid YYYY-MM-DD; not in the future.
 *  - Payment mode: required (must be a known mode).
 *  - Notes: optional; max 500 characters.
 *
 * `validateExpenseForm` is the single shared schema used by both create and edit
 * (US-09: "create and edit share one validation schema").
 *
 * Returns an object whose keys are `ExpenseFormValues` field names and whose
 * values are human-readable error strings.  An empty object means the form is
 * valid.
 *
 * `amountToPaise` converts a valid amount string to integer paise.
 */

import type { ExpenseFormErrors, ExpenseFormValues, PaymentMode } from '../types';
import { CATEGORIES, PAYMENT_MODES } from '../types';

const MAX_AMOUNT_INR = 10_000_000; // ₹1 crore

/** Parse a decimal rupee string to integer paise. Returns NaN on invalid input. */
export function amountToPaise(raw: string): number {
  const trimmed = raw.trim();
  if (!trimmed) return NaN;
  // Allow at most two decimal places
  const parsed = parseFloat(trimmed);
  if (isNaN(parsed)) return NaN;
  // Round to avoid floating-point drift
  return Math.round(parsed * 100);
}

/** Returns true when the amount string is a valid INR value for the form. */
export function isValidAmount(raw: string): boolean {
  const trimmed = raw.trim();
  if (!trimmed) return false;

  // Must be a positive number with at most 2 decimal places
  const numericPattern = /^\d+(\.\d{1,2})?$/;
  if (!numericPattern.test(trimmed)) return false;

  const parsed = parseFloat(trimmed);
  if (isNaN(parsed) || parsed <= 0) return false;
  if (parsed > MAX_AMOUNT_INR) return false;

  return true;
}

const DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;

function isValidDate(dateStr: string): boolean {
  if (!DATE_REGEX.test(dateStr)) return false;
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return false;
  // Must not be in the future
  const today = new Date();
  today.setHours(23, 59, 59, 999);
  return d <= today;
}

const KNOWN_CATEGORY_IDS = new Set(CATEGORIES.map((c) => c.id));
const KNOWN_PAYMENT_MODES = new Set<string>(PAYMENT_MODES);

export function validateExpenseForm(
  values: ExpenseFormValues
): ExpenseFormErrors {
  const errors: ExpenseFormErrors = {};

  // Amount
  if (!values.amountRaw.trim()) {
    errors.amountRaw = 'Amount is required.';
  } else if (!isValidAmount(values.amountRaw)) {
    const parsed = parseFloat(values.amountRaw.trim());
    if (!isNaN(parsed) && parsed > MAX_AMOUNT_INR) {
      errors.amountRaw = `Amount cannot exceed ₹${MAX_AMOUNT_INR.toLocaleString('en-IN')}.`;
    } else if (!isNaN(parsed) && parsed <= 0) {
      errors.amountRaw = 'Amount must be greater than zero.';
    } else {
      errors.amountRaw = 'Enter a valid amount (e.g. 250 or 1234.50).';
    }
  }

  // Category
  if (!values.categoryId) {
    errors.categoryId = 'Please select a category.';
  } else if (!KNOWN_CATEGORY_IDS.has(values.categoryId)) {
    errors.categoryId = 'Please select a valid category.';
  }

  // Date
  if (!values.date) {
    errors.date = 'Date is required.';
  } else if (!isValidDate(values.date)) {
    const d = new Date(values.date);
    const today = new Date();
    today.setHours(23, 59, 59, 999);
    if (!isNaN(d.getTime()) && d > today) {
      errors.date = 'Date cannot be in the future.';
    } else {
      errors.date = 'Enter a valid date (YYYY-MM-DD).';
    }
  }

  // Payment mode
  if (!values.paymentMode) {
    errors.paymentMode = 'Please select a payment mode.';
  } else if (!KNOWN_PAYMENT_MODES.has(values.paymentMode as PaymentMode)) {
    errors.paymentMode = 'Please select a valid payment mode.';
  }

  // Notes (optional, max 500 chars)
  if (values.notes.length > 500) {
    errors.notes = `Notes must be 500 characters or fewer (${values.notes.length}/500).`;
  }

  return errors;
}
