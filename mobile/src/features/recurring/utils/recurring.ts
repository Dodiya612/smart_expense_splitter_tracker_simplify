/**
 * Pure helpers for recurring expenses (T-45 / US-14): dates in Asia/Kolkata,
 * the rule created from the expense form, labels, actions and error text.
 * No React Native imports, so they are unit tested (scripts/test-recurring.mjs).
 *
 * Date maths match backend/app/services/recurring_service.py: occurrence n is
 * counted from the anchor date, and a monthly date on the 29th–31st falls on
 * the last day of shorter months.
 */

import { CATEGORIES, type ExpenseFormValues } from '@/features/expenses/types';
import { fromServerCategoryId, toServerCategoryId } from '@/features/expenses/utils/categoryIds';
import { expenseDescription } from '@/features/expenses/utils/expensePayload';
import { amountToPaise } from '@/features/expenses/utils/validation';
import type {
  CreateRecurringRuleBody,
  RecurringRule,
  RepeatFrequency,
  RuleAction,
  RuleStatus,
} from '../types';

// ── Dates ─────────────────────────────────────────────────────────────────────

const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Today's date in Asia/Kolkata as YYYY-MM-DD (the server decides "today" the same way). */
export function kolkataToday(now: Date = new Date()): string {
  return new Date(now.getTime() + IST_OFFSET_MS).toISOString().slice(0, 10);
}

function parseIso(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split('-').map(Number);
  return { y, m, d };
}

function toIso(y: number, m: number, d: number): string {
  return `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

function daysInMonth(y: number, m: number): number {
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

/** `anchor` moved by `n` periods; months and years clamp the day to the month's length. */
export function addPeriods(anchor: string, frequency: RepeatFrequency, n: number): string {
  const { y, m, d } = parseIso(anchor);
  if (frequency === 'daily' || frequency === 'weekly') {
    const days = frequency === 'daily' ? n : 7 * n;
    const t = new Date(Date.UTC(y, m - 1, d + days));
    return toIso(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
  }
  const months = frequency === 'monthly' ? n : 12 * n;
  const total = m - 1 + months;
  const year = y + Math.floor(total / 12);
  const month = (total % 12) + 1;
  return toIso(year, month, Math.min(d, daysInMonth(year, month)));
}

/**
 * The first repeat of an expense dated `expenseDate`: one period later, moved on
 * until it is today or later (the server only accepts a start date from today).
 * The expense itself is saved by the form, so the repeat never starts on its date.
 */
export function firstRepeatDate(
  expenseDate: string,
  frequency: RepeatFrequency,
  today: string
): string {
  let n = 1;
  let next = addPeriods(expenseDate, frequency, n);
  // A daily repeat of an old expense jumps straight to today instead of looping.
  if (frequency === 'daily' && next < today) return today;
  while (next < today && n < 5000) {
    n += 1;
    next = addPeriods(expenseDate, frequency, n);
  }
  return next;
}

/** "21 Dec 2026" */
export function formatShortDate(iso: string): string {
  const { y, m, d } = parseIso(iso);
  if (!y || !m || !d) return iso;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

// ── Labels ────────────────────────────────────────────────────────────────────

export const FREQUENCY_OPTIONS: readonly { id: RepeatFrequency; label: string }[] = [
  { id: 'daily', label: 'Daily' },
  { id: 'weekly', label: 'Weekly' },
  { id: 'monthly', label: 'Monthly' },
  { id: 'yearly', label: 'Yearly' },
];

export function frequencyLabel(frequency: RepeatFrequency): string {
  return FREQUENCY_OPTIONS.find((f) => f.id === frequency)?.label ?? frequency;
}

export const STATUS_LABELS: Record<RuleStatus, string> = {
  active: 'Active',
  paused: 'Paused',
  cancelled: 'Cancelled',
};

export function categoryLabel(serverCategoryId: string): string {
  const formId = fromServerCategoryId(serverCategoryId);
  return CATEGORIES.find((c) => c.id === formId)?.label ?? 'Other';
}

/** The line under a rule's name, e.g. "Next: 21 Dec 2026 (reminder the day before)". */
export function nextRunText(rule: Pick<RecurringRule, 'status' | 'nextRunDate'>): string {
  if (rule.status === 'cancelled') return 'Cancelled. No more expenses will be added.';
  if (rule.status === 'paused') return 'Paused. Nothing is added until you resume.';
  if (!rule.nextRunDate) return 'Ended. No more expenses will be added.';
  return `Next: ${formatShortDate(rule.nextRunDate)} (reminder the day before)`;
}

/** Which buttons a rule shows. Cancel is final, so a cancelled rule has none. */
export function allowedActions(status: RuleStatus): RuleAction[] {
  if (status === 'active') return ['pause', 'cancel'];
  if (status === 'paused') return ['resume', 'cancel'];
  return [];
}

/** Active first, then paused, then cancelled; newest first inside each (server order). */
export function sortRules(rules: readonly RecurringRule[]): RecurringRule[] {
  const rank: Record<RuleStatus, number> = { active: 0, paused: 1, cancelled: 2 };
  return rules
    .map((rule, index) => ({ rule, index }))
    .sort((a, b) => rank[a.rule.status] - rank[b.rule.status] || a.index - b.index)
    .map((x) => x.rule);
}

// ── Wire mapping ──────────────────────────────────────────────────────────────

type Raw = Record<string, unknown>;
const asString = (v: unknown): string => (typeof v === 'string' ? v : '');
const asNullableString = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const FREQUENCIES: readonly string[] = ['daily', 'weekly', 'monthly', 'yearly'];
const STATUSES: readonly string[] = ['active', 'paused', 'cancelled'];

export function mapRule(raw: unknown): RecurringRule {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Raw;
  const frequency = asString(r.frequency);
  const status = asString(r.status);
  return {
    id: asString(r.id),
    groupId: asNullableString(r.groupId),
    frequency: (FREQUENCIES.includes(frequency) ? frequency : 'monthly') as RepeatFrequency,
    startDate: asString(r.startDate),
    endDate: asNullableString(r.endDate),
    nextRunDate: asNullableString(r.nextRunDate),
    status: (STATUSES.includes(status) ? status : 'active') as RuleStatus,
    amountPaise: typeof r.amountPaise === 'number' ? r.amountPaise : 0,
    categoryId: asString(r.categoryId),
    description: asString(r.description),
    notes: asNullableString(r.notes),
    paymentMode: asNullableString(r.paymentMode),
  };
}

/** The rule created when "Repeat this expense" is on in the add-expense form. */
export function ruleFromExpenseForm(
  values: ExpenseFormValues,
  today: string
): CreateRecurringRuleBody {
  const notes = values.notes.trim();
  return {
    frequency: values.frequency,
    startDate: firstRepeatDate(values.date, values.frequency, today),
    amountPaise: amountToPaise(values.amountRaw),
    categoryId: toServerCategoryId(values.categoryId),
    description: expenseDescription(notes, values.categoryId),
    ...(notes ? { notes } : {}),
    paymentMode: values.paymentMode,
  };
}

/** The rule's own idempotency key: derived from the expense's key so a retry replays both. */
export function ruleIdempotencyKey(expenseKey: string): string {
  return `${expenseKey}:recurring`;
}

// ── Messages ──────────────────────────────────────────────────────────────────

export const REPEAT_NOT_SET_UP =
  'Your expense was saved, but the repeat could not be set up. Tap Try again – the expense will not be added twice.';

const ACTION_ERRORS: Record<string, string> = {
  RULE_NOT_ACTIVE: 'This repeat is not active any more. Pull down to refresh.',
  RULE_NOT_PAUSED: 'This repeat is not paused any more. Pull down to refresh.',
  RULE_CANCELLED: 'This repeat was cancelled, so it can no longer be changed.',
  RECURRING_RULE_NOT_FOUND: 'This repeat no longer exists. Pull down to refresh.',
};

export function actionErrorMessage(code: string, fallback: string): string {
  return ACTION_ERRORS[code] ?? fallback;
}

/** Cancelling is final, so it asks first. Pause and resume act straight away. */
export function cancelConfirmText(rule: Pick<RecurringRule, 'description'>): {
  title: string;
  message: string;
} {
  return {
    title: `Cancel "${rule.description}"?`,
    message:
      'No more expenses will be added and it cannot be restarted. Expenses already added stay in your history.',
  };
}

/** Shown after an action works, e.g. "Paused. Nothing is added until you resume." */
export function actionDoneText(action: RuleAction): string {
  if (action === 'pause') return 'Paused. Nothing is added until you resume.';
  if (action === 'resume') return 'Resumed. It continues from its next date; paused dates are not added.';
  return 'Cancelled. No more expenses will be added.';
}
