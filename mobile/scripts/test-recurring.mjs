import test from 'node:test';
import assert from 'node:assert';
import {
  addPeriods,
  allowedActions,
  cancelConfirmText,
  categoryLabel,
  firstRepeatDate,
  formatShortDate,
  kolkataToday,
  mapRule,
  nextRunText,
  ruleFromExpenseForm,
  ruleIdempotencyKey,
  sortRules,
} from '../src/features/recurring/utils/recurring.ts';
import { createRecurringRule, changeRecurringRule } from '../src/features/recurring/services/recurringApi.ts';
import { fromServerCategoryId, toServerCategoryId } from '../src/features/expenses/utils/categoryIds.ts';
import { buildCreateExpenseBody, expenseDescription } from '../src/features/expenses/utils/expensePayload.ts';
import { createExpense, mapBackendExpenseToDomain } from '../src/features/expenses/services/expenseApi.ts';
import { CATEGORIES } from '../src/features/expenses/types.ts';
import { validateExpenseForm } from '../src/features/expenses/utils/validation.ts';
import { notificationTarget } from '../src/features/notifications/utils/parseNotifications.ts';
import { fastApiClient } from '../src/services/api/fastApiClient.ts';

const FOOD_ID = '00000000-0000-4000-8000-000000000001';
const RENT_ID = '00000000-0000-4000-8000-000000000006';

const FORM = Object.freeze({
  amountRaw: '15000',
  categoryId: 'rent',
  date: '2026-11-01',
  paymentMode: 'upi',
  notes: 'Flat rent',
  isRecurring: true,
  frequency: 'monthly',
});

function rawRule(over = {}) {
  return {
    id: 'r1',
    groupId: null,
    frequency: 'monthly',
    startDate: '2026-12-01',
    endDate: null,
    nextRunDate: '2026-12-01',
    status: 'active',
    amountPaise: 1500000,
    categoryId: RENT_ID,
    description: 'Flat rent',
    notes: null,
    merchant: null,
    paymentMode: 'upi',
    split: null,
    createdAt: '2026-11-21T10:00:00Z',
    updatedAt: '2026-11-21T10:00:00Z',
    pausedAt: null,
    cancelledAt: null,
    ...over,
  };
}

/** Swap fastApiClient.post for one test and record what was sent. */
async function capturePost(response, run) {
  const original = fastApiClient.post;
  const calls = [];
  fastApiClient.post = async (endpoint, body, headers) => {
    calls.push({ endpoint, body, headers });
    return typeof response === 'function' ? response(endpoint, body) : response;
  };
  try {
    await run(calls);
  } finally {
    fastApiClient.post = original;
  }
}

test('T-45 / US-14: dates follow the server rules (Asia/Kolkata, month-end clamp)', () => {
  // 18:31 UTC is already the next day in India.
  assert.strictEqual(kolkataToday(new Date('2026-11-20T18:31:00Z')), '2026-11-21');
  assert.strictEqual(kolkataToday(new Date('2026-11-20T18:29:00Z')), '2026-11-20');

  assert.strictEqual(addPeriods('2026-01-31', 'monthly', 1), '2026-02-28');
  assert.strictEqual(addPeriods('2028-01-31', 'monthly', 1), '2028-02-29');
  assert.strictEqual(addPeriods('2026-01-31', 'monthly', 2), '2026-03-31'); // back to the 31st
  assert.strictEqual(addPeriods('2026-12-15', 'monthly', 1), '2027-01-15');
  assert.strictEqual(addPeriods('2028-02-29', 'yearly', 1), '2029-02-28');
  assert.strictEqual(addPeriods('2026-12-30', 'weekly', 1), '2027-01-06');
  assert.strictEqual(addPeriods('2026-12-31', 'daily', 1), '2027-01-01');
  assert.strictEqual(formatShortDate('2026-12-21'), '21 Dec 2026');
});

test('T-45: the repeat starts one period after the saved expense, never on its date or in the past', () => {
  const today = '2026-11-21';
  assert.strictEqual(firstRepeatDate('2026-11-21', 'monthly', today), '2026-12-21');
  assert.strictEqual(firstRepeatDate('2026-11-21', 'daily', today), '2026-11-22');
  assert.strictEqual(firstRepeatDate('2026-11-21', 'weekly', today), '2026-11-28');
  assert.strictEqual(firstRepeatDate('2026-11-21', 'yearly', today), '2027-11-21');
  // An older expense: the next date that is today or later, on the same schedule.
  assert.strictEqual(firstRepeatDate('2026-11-01', 'monthly', today), '2026-12-01');
  assert.strictEqual(firstRepeatDate('2026-10-31', 'monthly', today), '2026-11-30');
  assert.strictEqual(firstRepeatDate('2026-11-07', 'weekly', today), '2026-11-21');
  assert.strictEqual(firstRepeatDate('2026-01-05', 'daily', today), today);
  // Tomorrow's expense (the server allows it) repeats the day after.
  assert.strictEqual(firstRepeatDate('2026-11-22', 'daily', today), '2026-11-23');
});

test('T-45 criterion 1: marking an expense as recurring creates the right rule', () => {
  const body = ruleFromExpenseForm(FORM, '2026-11-21');
  assert.deepStrictEqual(body, {
    frequency: 'monthly',
    startDate: '2026-12-01',
    amountPaise: 1500000,
    categoryId: RENT_ID,
    description: 'Flat rent',
    notes: 'Flat rent',
    paymentMode: 'upi',
  });
  assert.ok(Number.isInteger(body.amountPaise));
  // Empty notes: the category name becomes the description, and no notes are sent.
  const noNotes = ruleFromExpenseForm({ ...FORM, notes: '  ', frequency: 'weekly' }, '2026-11-21');
  assert.strictEqual(noNotes.description, 'Rent & Housing');
  assert.strictEqual('notes' in noNotes, false);
  // Expense and rule keys differ (the server's keys are unique per user) but are stable for retries.
  assert.strictEqual(ruleIdempotencyKey('k-1'), 'k-1:recurring');
  assert.strictEqual(ruleIdempotencyKey('k-1'), ruleIdempotencyKey('k-1'));
});

test('T-45 (finishing T-19): every form category maps to a seeded server category and back', () => {
  const serverIds = new Set();
  for (const cat of CATEGORIES) {
    const serverId = toServerCategoryId(cat.id);
    assert.match(serverId, /^00000000-0000-4000-8000-0000000000(0[1-9]|1[0-2])$/, cat.id);
    assert.strictEqual(fromServerCategoryId(serverId), cat.id);
    serverIds.add(serverId);
    // Every category still passes the form's validation.
    const errors = validateExpenseForm({ ...FORM, categoryId: cat.id, isRecurring: false });
    assert.strictEqual(errors.categoryId, undefined, cat.id);
  }
  assert.strictEqual(serverIds.size, 12);
  assert.strictEqual(fromServerCategoryId(FOOD_ID.toUpperCase()), 'food');
  assert.strictEqual(fromServerCategoryId('custom-id'), 'custom-id'); // unknown ids pass through
  assert.strictEqual(categoryLabel(RENT_ID), 'Rent & Housing');
});

test('T-45 (finishing T-19): create-expense body uses paise, a UUID category and a description', () => {
  const body = buildCreateExpenseBody({
    amountPaise: 25000,
    categoryId: 'food',
    date: '2026-11-21',
    paymentMode: 'card',
    notes: '  Lunch  ',
    isRecurring: false,
    idempotencyKey: 'k',
  });
  assert.deepStrictEqual(body, {
    amountPaise: 25000,
    description: 'Lunch',
    categoryId: FOOD_ID,
    expenseDate: '2026-11-21',
    paymentMode: 'card',
    notes: 'Lunch',
  });
  assert.strictEqual(expenseDescription('', 'food'), 'Food & Drink');
  assert.strictEqual(expenseDescription('x'.repeat(400), 'food').length, 255);
});

test('T-45: createExpense posts to the server with the Idempotency-Key and reads the camelCase reply', async () => {
  const reply = {
    data: {
      id: 'e1',
      userId: 'u1',
      categoryId: FOOD_ID,
      amountMinor: 25000,
      amountPaise: 25000,
      description: 'Lunch',
      expenseDate: '2026-11-21',
      occurredOn: '2026-11-21',
      notes: 'Lunch',
      paymentMode: 'card',
      version: 1,
      createdAt: '2026-11-21T08:00:00Z',
      updatedAt: '2026-11-21T08:00:00Z',
    },
  };
  await capturePost(reply, async (calls) => {
    const saved = await createExpense({
      amountPaise: 25000,
      categoryId: 'food',
      date: '2026-11-21',
      paymentMode: 'card',
      notes: 'Lunch',
      isRecurring: false,
      idempotencyKey: 'key-123',
    });
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].endpoint, '/api/v1/expenses');
    assert.strictEqual(calls[0].headers['Idempotency-Key'], 'key-123');
    assert.strictEqual(calls[0].body.categoryId, FOOD_ID);
    assert.strictEqual(saved.id, 'e1');
    assert.strictEqual(saved.amountPaise, 25000);
    assert.strictEqual(saved.categoryId, 'food');
    assert.strictEqual(saved.date, '2026-11-21');
    assert.strictEqual(saved.paymentMode, 'card');
  });
  // Old snake_case data still maps (the existing tests rely on it).
  const old = mapBackendExpenseToDomain({
    id: 'e2', user_id: 'u1', category_id: 'food', amount_minor: 100, description: 'Tea',
    expense_date: '2026-11-01', version: 1, created_at: 'x', updated_at: 'y',
  });
  assert.strictEqual(old.amountPaise, 100);
  assert.strictEqual(old.date, '2026-11-01');
});

test('T-45: rule create and actions call the T-44 endpoints', async () => {
  await capturePost({ data: rawRule() }, async (calls) => {
    const rule = await createRecurringRule(ruleFromExpenseForm(FORM, '2026-11-21'), 'k-1:recurring');
    assert.strictEqual(calls[0].endpoint, '/api/v1/recurring');
    assert.strictEqual(calls[0].headers['Idempotency-Key'], 'k-1:recurring');
    assert.strictEqual(rule.nextRunDate, '2026-12-01');
  });
  await capturePost((endpoint) => ({ data: rawRule({ status: endpoint.endsWith('/pause') ? 'paused' : 'active' }) }), async (calls) => {
    const paused = await changeRecurringRule('r1', 'pause');
    assert.strictEqual(calls[0].endpoint, '/api/v1/recurring/r1/pause');
    assert.strictEqual(paused.status, 'paused');
    await changeRecurringRule('r1', 'resume');
    assert.strictEqual(calls[1].endpoint, '/api/v1/recurring/r1/resume');
    await changeRecurringRule('r1', 'cancel');
    assert.strictEqual(calls[2].endpoint, '/api/v1/recurring/r1/cancel');
  });
});

test('T-45 criterion 4: pause, resume and cancel buttons follow the rule status', () => {
  assert.deepStrictEqual(allowedActions('active'), ['pause', 'cancel']);
  assert.deepStrictEqual(allowedActions('paused'), ['resume', 'cancel']);
  assert.deepStrictEqual(allowedActions('cancelled'), []); // cancel is final

  assert.strictEqual(nextRunText(mapRule(rawRule())), 'Next: 1 Dec 2026 (reminder the day before)');
  assert.match(nextRunText(mapRule(rawRule({ status: 'paused' }))), /^Paused/);
  assert.match(nextRunText(mapRule(rawRule({ status: 'cancelled', nextRunDate: null }))), /^Cancelled/);
  assert.match(nextRunText(mapRule(rawRule({ nextRunDate: null }))), /^Ended/);
  assert.match(cancelConfirmText({ description: 'Flat rent' }).message, /cannot be restarted/);

  const sorted = sortRules([
    mapRule(rawRule({ id: 'c', status: 'cancelled' })),
    mapRule(rawRule({ id: 'p', status: 'paused' })),
    mapRule(rawRule({ id: 'a1' })),
    mapRule(rawRule({ id: 'a2' })),
  ]);
  assert.deepStrictEqual(sorted.map((r) => r.id), ['a1', 'a2', 'p', 'c']);
});

test('T-45 criterion 3: the day-before reminder opens the recurring list', () => {
  const base = { id: 'n1', title: '', body: '', groupId: null, groupName: null, isRead: false, createdAt: '' };
  assert.deepStrictEqual(notificationTarget({ ...base, kind: 'recurring_expense_upcoming' }), { pathname: '/recurring' });
  assert.deepStrictEqual(notificationTarget({ ...base, kind: 'recurring_expense_skipped', groupId: 'g1' }), {
    pathname: '/recurring',
  });
});

test('T-45: unexpected wire values fall back safely', () => {
  const rule = mapRule({ id: 'x', frequency: 'hourly', status: 'weird' });
  assert.strictEqual(rule.frequency, 'monthly');
  assert.strictEqual(rule.status, 'active');
  assert.strictEqual(rule.amountPaise, 0);
  assert.strictEqual(mapRule(null).id, '');
});
