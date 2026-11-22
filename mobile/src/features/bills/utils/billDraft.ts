/**
 * Pure helpers for the bill review flow (T-54 / US-16): wire mapping, the
 * pre-filled form, highlighted fields and error text. No React Native imports,
 * so they are unit tested (scripts/test-bills.mjs).
 *
 * The scan only produces a draft. The expense is saved when the user taps
 * "Confirm and save" on the reviewed form, with the receipt id attached.
 */

import type { ExpenseFormValues } from '@/features/expenses/types';
import { paiseToInputText } from '@/utils/money';
import type { BillDraft, BillLineItem, BillWarning, PickedBillImage, ReviewField } from '../types';

/** The server accepts uploads up to 5 MB (it then shrinks them below 1 MB). */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

/** Server category names (rule parser) -> the form's category ids. */
const CATEGORY_BY_NAME: Record<string, string> = {
  'food & dining': 'food',
  groceries: 'groceries',
  'travel & transport': 'transport',
  shopping: 'shopping',
  'bills & utilities': 'utilities',
  'rent & housing': 'rent',
  entertainment: 'entertainment',
  health: 'health',
  education: 'education',
  'personal care': 'personal_care',
  'gifts & donations': 'gifts',
  other: 'other',
};

const FORM_CATEGORY_IDS: readonly string[] = Object.values(CATEGORY_BY_NAME);

export function categoryFromBill(name: string | null | undefined): string | null {
  if (!name) return null;
  return CATEGORY_BY_NAME[name.trim().toLowerCase()] ?? null;
}

// ── Wire mapping ──────────────────────────────────────────────────────────────

type Raw = Record<string, unknown>;
const asRecord = (v: unknown): Raw => (v && typeof v === 'object' ? (v as Raw) : {});
const asString = (v: unknown): string => (typeof v === 'string' ? v : '');
const asPaise = (v: unknown): number | null =>
  typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : null;
const FIELDS: readonly string[] = ['amount', 'date', 'merchant', 'items'];
const asField = (v: unknown): ReviewField | null =>
  typeof v === 'string' && FIELDS.includes(v) ? (v as ReviewField) : null;

function mapItem(raw: unknown): BillLineItem | null {
  const r = asRecord(raw);
  const amountPaise = asPaise(r.amountPaise);
  const name = asString(r.name).trim();
  if (!name || amountPaise === null) return null;
  return {
    name,
    amountPaise,
    quantity: asString(r.quantity) || null,
    unitPricePaise: asPaise(r.unitPricePaise),
  };
}

function mapWarning(raw: unknown): BillWarning | null {
  const r = asRecord(raw);
  const message = asString(r.message);
  if (!message) return null;
  return { code: asString(r.code) || 'CHECK', message, field: asField(r.field) };
}

/** POST /api/v1/receipts/scan reply -> BillDraft. Unknown or bad values are dropped. */
export function mapScanResponse(raw: unknown): BillDraft {
  const d = asRecord(asRecord(raw).data);
  const source = asString(d.itemsSource);
  const date = asString(d.expenseDate);
  return {
    receiptId: asString(d.receiptId),
    merchant: asString(d.merchant).trim() || null,
    amountPaise: asPaise(d.amountPaise) ?? asPaise(d.amountMinor),
    date: /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null,
    categoryId: categoryFromBill(asString(d.category)),
    items: (Array.isArray(d.items) ? d.items : []).map(mapItem).filter((i): i is BillLineItem => i !== null),
    itemsSource: source === 'llm' || source === 'rules' ? source : 'none',
    warnings: (Array.isArray(d.warnings) ? d.warnings : [])
      .map(mapWarning)
      .filter((w): w is BillWarning => w !== null),
    lowConfidenceFields: (Array.isArray(d.lowConfidenceFields) ? d.lowConfidenceFields : [])
      .map(asField)
      .filter((f): f is ReviewField => f !== null),
  };
}

// ── Route param (the draft travels to /add-expense as JSON) ────────────────────

export function encodeDraft(draft: BillDraft): string {
  return JSON.stringify(draft);
}

/** Parses the route param; anything malformed opens a normal empty form instead. */
export function decodeDraft(param: string | undefined): BillDraft | undefined {
  if (!param) return undefined;
  try {
    const saved = asRecord(JSON.parse(param) as unknown);
    const draft = mapScanResponse({ data: { ...saved, expenseDate: saved.date, category: null } });
    const categoryId = asString(saved.categoryId);
    draft.categoryId = FORM_CATEGORY_IDS.includes(categoryId) ? categoryId : null;
    return draft.receiptId ? draft : undefined;
  } catch {
    return undefined;
  }
}

// ── Pre-filled form ───────────────────────────────────────────────────────────

/** The add-expense form filled from the bill. Missing values stay empty for the user. */
export function draftToFormValues(draft: BillDraft, today: string): ExpenseFormValues {
  return {
    amountRaw: draft.amountPaise !== null ? paiseToInputText(draft.amountPaise) : '',
    categoryId: draft.categoryId ?? '',
    date: draft.date ?? today,
    paymentMode: 'upi',
    notes: draft.merchant ?? '',
    isRecurring: false,
    frequency: 'monthly',
  };
}

/** The message shown under a highlighted field, or null when the field looks fine. */
export function fieldWarning(draft: BillDraft | undefined, field: ReviewField): string | null {
  if (!draft || !draft.lowConfidenceFields.includes(field)) return null;
  return draft.warnings.find((w) => w.field === field)?.message ?? 'Please check this value.';
}

/** Warnings that are not tied to one field (shown at the top of the form). */
export function generalWarnings(draft: BillDraft | undefined): BillWarning[] {
  if (!draft) return [];
  return draft.warnings.filter((w) => w.field === null || w.field === 'items');
}

// ── Picking and errors ────────────────────────────────────────────────────────

/** Why a picked file can't be uploaded, or null when it's fine. */
export function pickedImageProblem(image: PickedBillImage): string | null {
  const type = image.mimeType.toLowerCase();
  if (type && type !== 'image/jpeg' && type !== 'image/jpg' && type !== 'image/png') {
    return 'Please choose a JPEG or PNG photo of the bill.';
  }
  if (image.fileSize !== null && image.fileSize > MAX_UPLOAD_BYTES) {
    return 'This photo is larger than 5 MB. Please take a new photo or choose a smaller one.';
  }
  return null;
}

const SCAN_ERRORS: Record<string, string> = {
  UNSUPPORTED_MEDIA_TYPE: 'Please choose a JPEG or PNG photo of the bill.',
  INVALID_IMAGE: "This photo couldn't be opened. Please take a new photo.",
  IMAGE_TOO_LARGE: 'This photo is larger than 5 MB. Please take a new photo or choose a smaller one.',
  AI_QUOTA_EXCEEDED: "You've used today's bill scans. You can still add the expense by hand.",
  REQUEST_TIMEOUT: 'Reading the bill took too long. Try again, or add the expense by hand.',
  NETWORK_ERROR: "Couldn't reach the server. Check your connection and try again.",
};

export function scanErrorMessage(code: string, fallback: string): string {
  return SCAN_ERRORS[code] ?? fallback;
}

/** "2 × ₹120.00" for an item row, or null when the bill didn't print both. */
export function itemDetail(item: BillLineItem, format: (paise: number) => string): string | null {
  if (item.quantity && item.unitPricePaise !== null) return `${item.quantity} × ${format(item.unitPricePaise)}`;
  if (item.quantity) return `Qty ${item.quantity}`;
  return null;
}
