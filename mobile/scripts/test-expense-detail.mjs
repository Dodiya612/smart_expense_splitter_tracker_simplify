import test from 'node:test';
import assert from 'node:assert';

import {
  CATEGORIES,
  PAYMENT_MODE_LABELS,
} from '../src/features/expenses/types.ts';

// ---------------------------------------------------------------------------
// Pure helper functions matching ExpenseDetailScreen implementation
// ---------------------------------------------------------------------------

function formatPaiseToInr(amountPaise) {
  const inrValue = amountPaise / 100;
  return inrValue.toLocaleString('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatFullDateTime(dateStr, createdAtStr) {
  const target = createdAtStr || dateStr;
  if (!target) return '—';
  try {
    const d = new Date(target);
    if (isNaN(d.getTime())) return dateStr || '—';
    const hasTime = !!createdAtStr && createdAtStr.includes('T');
    return d.toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: hasTime ? 'numeric' : undefined,
      minute: hasTime ? '2-digit' : undefined,
      hour12: true,
    });
  } catch {
    return dateStr || '—';
  }
}

function resolveExpenseParam(rawParam) {
  if (!rawParam) return undefined;
  try {
    return JSON.parse(rawParam);
  } catch {
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// 1. Currency Formatting Unit Tests (Integer Paise -> INR, NFR-M01)
// ---------------------------------------------------------------------------
test('formatPaiseToInr currency formatting', async (t) => {
  await t.test('formats positive integer paise correctly in standard INR notation', () => {
    assert.strictEqual(formatPaiseToInr(149950), '₹1,499.50');
    assert.strictEqual(formatPaiseToInr(34900), '₹349.00');
    assert.strictEqual(formatPaiseToInr(120000), '₹1,200.00');
    assert.strictEqual(formatPaiseToInr(5000000), '₹50,000.00');
  });

  await t.test('formats zero and single-digit paise properly', () => {
    assert.strictEqual(formatPaiseToInr(0), '₹0.00');
    assert.strictEqual(formatPaiseToInr(5), '₹0.05');
    assert.strictEqual(formatPaiseToInr(50), '₹0.50');
  });

  await t.test('handles large amounts with Indian comma grouping', () => {
    assert.strictEqual(formatPaiseToInr(100000000), '₹10,00,000.00');
  });
});

// ---------------------------------------------------------------------------
// 2. Date and Time Formatting Unit Tests
// ---------------------------------------------------------------------------
test('formatFullDateTime date/time formatting', async (t) => {
  await t.test('formats ISO timestamp with date and time', () => {
    const result = formatFullDateTime('2026-10-31', '2026-10-31T10:30:00Z');
    assert.ok(result.includes('2026'));
    assert.ok(result.includes('Oct'));
    // Should include time indicator
    assert.ok(result.toLowerCase().includes('pm') || result.toLowerCase().includes('am'));
  });

  await t.test('falls back to dateStr when createdAt is missing', () => {
    const result = formatFullDateTime('2026-10-31');
    assert.ok(result.includes('2026'));
    assert.ok(result.includes('Oct'));
  });

  await t.test('returns dash for undefined date and timestamp', () => {
    assert.strictEqual(formatFullDateTime(undefined, undefined), '—');
    assert.strictEqual(formatFullDateTime('', ''), '—');
  });

  await t.test('gracefully handles invalid date string without throwing', () => {
    const result = formatFullDateTime('invalid-date');
    assert.strictEqual(result, 'invalid-date');
  });
});

// ---------------------------------------------------------------------------
// 3. Category & Payment Mode Metadata Lookup Tests
// ---------------------------------------------------------------------------
test('ExpenseDetailScreen metadata lookup integrity', async (t) => {
  await t.test('resolves known category ids to labels and valid palette indices', () => {
    const food = CATEGORIES.find((c) => c.id === 'food');
    assert.ok(food);
    assert.strictEqual(food.label, 'Food & Drink');
    assert.strictEqual(typeof food.paletteIndex, 'number');

    const transport = CATEGORIES.find((c) => c.id === 'transport');
    assert.ok(transport);
    assert.strictEqual(transport.label, 'Transport');

    const utilities = CATEGORIES.find((c) => c.id === 'utilities');
    assert.ok(utilities);
    assert.strictEqual(utilities.label, 'Utilities');
  });

  await t.test('resolves payment mode labels correctly', () => {
    assert.strictEqual(PAYMENT_MODE_LABELS.upi, 'UPI');
    assert.strictEqual(PAYMENT_MODE_LABELS.card, 'Card');
    assert.strictEqual(PAYMENT_MODE_LABELS.cash, 'Cash');
    assert.strictEqual(PAYMENT_MODE_LABELS.net_banking, 'Net Banking');
    assert.strictEqual(PAYMENT_MODE_LABELS.wallet, 'Wallet');
    assert.strictEqual(PAYMENT_MODE_LABELS.other, 'Other');
  });
});

// ---------------------------------------------------------------------------
// 4. Safe Param Parsing & Fallback Logic Tests
// ---------------------------------------------------------------------------
test('ExpenseDetailScreen safe param parsing', async (t) => {
  await t.test('safely parses valid stringified expense JSON', () => {
    const sample = {
      id: 'exp-detail-1',
      amountPaise: 250000,
      categoryId: 'travel',
      date: '2026-11-01',
      paymentMode: 'card',
      notes: 'Flight booking to Mumbai',
      merchant: 'IndiGo',
      isRecurring: false,
      version: 1,
      createdAt: '2026-11-01T10:00:00Z',
      updatedAt: '2026-11-01T10:00:00Z',
    };

    const rawParam = JSON.stringify(sample);
    const parsed = resolveExpenseParam(rawParam);

    assert.ok(parsed);
    assert.strictEqual(parsed.id, 'exp-detail-1');
    assert.strictEqual(parsed.amountPaise, 250000);
    assert.strictEqual(parsed.merchant, 'IndiGo');
  });

  await t.test('catches malformed JSON gracefully and returns undefined', () => {
    const malformed = '{id: invalid, amount:';
    const result = resolveExpenseParam(malformed);
    assert.strictEqual(result, undefined);
  });

  await t.test('handles empty and null rawParam gracefully', () => {
    assert.strictEqual(resolveExpenseParam(null), undefined);
    assert.strictEqual(resolveExpenseParam(undefined), undefined);
    assert.strictEqual(resolveExpenseParam(''), undefined);
  });
});
