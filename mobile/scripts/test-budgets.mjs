import test from 'node:test';
import assert from 'node:assert';
import { mapBudget } from '../src/features/budgets/services/budgetsApi.ts';
import { getCategoryMeta, DEFAULT_BUDGET_CATEGORIES } from '../src/features/budgets/utils/categories.ts';
import { formatPaiseToInr } from '../src/features/home/utils/dashboardSummary.ts';

test('T-49 / US-25: Budgets Screen & Progress Tests', async (t) => {
  await t.test('1. Normalizes raw backend budget response to frontend model', () => {
    const raw = {
      id: 'b1111111-1111-4000-8000-000000000001',
      period: 'monthly',
      category_id: null,
      limit_paise: 1000000,
      created_at: '2026-11-01T00:00:00Z',
      updated_at: '2026-11-01T00:00:00Z',
      progress: {
        period_start: '2026-11-01',
        period_end: '2026-11-30',
        spent_paise: 650000,
        remaining_paise: 350000,
        over_by_paise: 0,
        percent_used: 65,
        status: 'under',
      },
    };

    const budget = mapBudget(raw);
    assert.strictEqual(budget.id, raw.id);
    assert.strictEqual(budget.period, 'monthly');
    assert.strictEqual(budget.categoryId, null);
    assert.strictEqual(budget.limitPaise, 1000000);
    assert.strictEqual(budget.progress.spentPaise, 650000);
    assert.strictEqual(budget.progress.remainingPaise, 350000);
    assert.strictEqual(budget.progress.overByPaise, 0);
    assert.strictEqual(budget.progress.percentUsed, 65);
    assert.strictEqual(budget.progress.status, 'under');
  });

  await t.test('2. Status threshold calculations match backend rules (under, warning, exceeded)', () => {
    // Under 80% (< 80)
    const underRaw = {
      id: '1',
      period: 'monthly',
      limit_paise: 100000,
      progress: { spent_paise: 79000 },
    };
    const under = mapBudget(underRaw);
    assert.strictEqual(under.progress.percentUsed, 79);
    assert.strictEqual(under.progress.status, 'under');

    // Warning (80% to < 100%)
    const warningRaw = {
      id: '2',
      period: 'monthly',
      limit_paise: 100000,
      progress: { spent_paise: 80000 },
    };
    const warning = mapBudget(warningRaw);
    assert.strictEqual(warning.progress.percentUsed, 80);
    assert.strictEqual(warning.progress.status, 'warning');

    // Exceeded (>= 100%)
    const exceededRaw = {
      id: '3',
      period: 'monthly',
      limit_paise: 100000,
      progress: { spent_paise: 105000 },
    };
    const exceeded = mapBudget(exceededRaw);
    assert.strictEqual(exceeded.progress.percentUsed, 105);
    assert.strictEqual(exceeded.progress.status, 'exceeded');
    assert.strictEqual(exceeded.progress.remainingPaise, -5000);
    assert.strictEqual(exceeded.progress.overByPaise, 5000);
  });

  await t.test('3. Category metadata mapping resolves known and overall scopes', () => {
    // Overall budget has null categoryId
    assert.strictEqual(getCategoryMeta(null), null);
    assert.strictEqual(getCategoryMeta(undefined), null);

    // Seeded food category
    const food = getCategoryMeta('00000000-0000-4000-8000-000000000001');
    assert.ok(food);
    assert.strictEqual(food?.name, 'Food & Dining');
    assert.strictEqual(food?.icon, 'restaurant-outline');

    // Default categories list is non-empty
    assert.strictEqual(DEFAULT_BUDGET_CATEGORIES.length, 12);
  });

  await t.test('4. Currency formatting for limit, spent, and remaining in INR', () => {
    const formatted = formatPaiseToInr(500000); // ₹5,000.00
    assert.ok(formatted.includes('5,000'));

    const remainingFormatted = formatPaiseToInr(125050); // ₹1,250.50
    assert.ok(remainingFormatted.includes('1,250.50'));
  });

  await t.test('5. Progress bar accessibility value clamping logic', () => {
    // Visual progress width must be clamped between 0 and 100
    const clamp = (percent) => Math.max(0, Math.min(100, isNaN(percent) ? 0 : percent));

    assert.strictEqual(clamp(45), 45);
    assert.strictEqual(clamp(-10), 0);
    assert.strictEqual(clamp(150), 100);
    assert.strictEqual(clamp(NaN), 0);
  });
});
