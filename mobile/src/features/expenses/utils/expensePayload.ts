/**
 * Request bodies for saving a personal expense (T-45, finishing T-19).
 * Pure functions so they are unit tested (scripts/test-recurring.mjs, test-bills.mjs).
 */

import { CATEGORIES, type CreateExpensePayload } from '../types';
import { toServerCategoryId } from './categoryIds';

/** The server's description limit (ExpenseCreate.description, max 255). */
export const DESCRIPTION_MAX = 255;

/**
 * The server needs a description, but the form only has optional notes.
 * Use the notes (cut to 255 characters), or the category name when they're empty.
 */
export function expenseDescription(notes: string, categoryId: string): string {
  const trimmed = notes.trim();
  if (trimmed) return trimmed.slice(0, DESCRIPTION_MAX).trim();
  return CATEGORIES.find((c) => c.id === categoryId)?.label ?? 'Expense';
}

/** The server's merchant limit (ExpenseCreate.merchant, max 255). */
export const MERCHANT_MAX = 255;

/**
 * Body for POST /api/v1/expenses (camelCase, money in integer paise).
 * A scanned bill adds `receiptId` (linked in the same transaction) and `merchant` (T-54).
 */
export function buildCreateExpenseBody(payload: CreateExpensePayload): Record<string, unknown> {
  const notes = payload.notes.trim();
  const merchant = payload.merchant?.trim().slice(0, MERCHANT_MAX).trim();
  return {
    amountPaise: payload.amountPaise,
    description: expenseDescription(notes, payload.categoryId),
    categoryId: toServerCategoryId(payload.categoryId),
    expenseDate: payload.date,
    paymentMode: payload.paymentMode,
    ...(notes ? { notes } : {}),
    ...(merchant ? { merchant } : {}),
    ...(payload.receiptId ? { receiptId: payload.receiptId } : {}),
  };
}
