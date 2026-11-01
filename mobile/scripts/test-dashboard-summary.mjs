import test from 'node:test';
import assert from 'node:assert';
import {
  formatPaiseToInr,
  getCurrentMonthLabel,
  calculateBudgetMetrics,
  calculateTotalSpentPaise,
  filterExpensesForCurrentMonth,
  isDashboardEmpty,
} from '../src/features/home/utils/dashboardSummary.ts';
import {
  getMockPopulatedDashboardData,
  getMockEmptyDashboardData,
} from '../src/features/home/data/mockDashboardData.ts';

test('1. Integer-Paise to INR Currency Formatting', async (t) => {
  await t.test('formats positive integer paise correctly in standard INR notation', () => {
    assert.strictEqual(formatPaiseToInr(0), '₹0.00');
    assert.strictEqual(formatPaiseToInr(100), '₹1.00');
    assert.strictEqual(formatPaiseToInr(45000), '₹450.00');
    assert.strictEqual(formatPaiseToInr(123456), '₹1,234.56');
    assert.strictEqual(formatPaiseToInr(2500000), '₹25,000.00');
  });

  await t.test('formats negative integer paise correctly', () => {
    assert.strictEqual(formatPaiseToInr(-115000), '-₹1,150.00');
    assert.strictEqual(formatPaiseToInr(-50), '-₹0.50');
  });

  await t.test('preserves two decimal places for single-digit paise', () => {
    assert.strictEqual(formatPaiseToInr(5), '₹0.05');
  });
});

test('2. Dynamic Month and Year Labeling', async (t) => {
  await t.test('derives correct localized month and year from reference date', () => {
    const nov2026 = new Date('2026-11-01T10:00:00Z');
    const label = getCurrentMonthLabel(nov2026);
    assert.ok(label.includes('November'));
    assert.ok(label.includes('2026'));
  });

  await t.test('works with current system date when no argument is supplied', () => {
    const label = getCurrentMonthLabel();
    assert.strictEqual(typeof label, 'string');
    assert.ok(label.length > 3);
  });
});

test('3. Monthly Spending Aggregation from Integer Paise', async (t) => {
  await t.test('sums multiple expense amounts in integer paise without precision loss', () => {
    const sampleExpenses = [
      { amountPaise: 45000 },
      { amountPaise: 120000 },
      { amountPaise: 285000 },
    ];
    // 450.00 + 1200.00 + 2850.00 = 4500.00
    const total = calculateTotalSpentPaise(sampleExpenses);
    assert.strictEqual(total, 450000);
    assert.strictEqual(formatPaiseToInr(total), '₹4,500.00');
  });

  await t.test('returns 0 paise when expense array is empty', () => {
    const total = calculateTotalSpentPaise([]);
    assert.strictEqual(total, 0);
  });
});

test('4. Budget Percentage & Remaining Calculations', async (t) => {
  await t.test('calculates safe remaining amount and percentage for normal usage', () => {
    const limit = 2500000; // ₹25,000.00
    const spent = 450000;  // ₹4,500.00 (18%)
    const metrics = calculateBudgetMetrics(limit, spent);

    assert.strictEqual(metrics.remainingPaise, 2050000); // ₹20,500.00
    assert.strictEqual(metrics.percentageSpent, 18);
  });

  await t.test('handles over-budget conditions safely with negative remaining paise', () => {
    const limit = 2000000; // ₹20,000.00
    const spent = 2500000; // ₹25,000.00 (125%)
    const metrics = calculateBudgetMetrics(limit, spent);

    assert.strictEqual(metrics.remainingPaise, -500000); // -₹5,000.00
    assert.strictEqual(metrics.percentageSpent, 100, 'Clamps percentage at 100 for visual bar');
  });

  await t.test('handles zero budget limit without NaN or division-by-zero error', () => {
    const metricsZero = calculateBudgetMetrics(0, 50000);
    assert.strictEqual(isNaN(metricsZero.percentageSpent), false);
    assert.strictEqual(metricsZero.percentageSpent, 0);
    assert.strictEqual(metricsZero.remainingPaise, 0);

    const metricsNegative = calculateBudgetMetrics(-1000, 50000);
    assert.strictEqual(isNaN(metricsNegative.percentageSpent), false);
    assert.strictEqual(metricsNegative.percentageSpent, 0);
    assert.strictEqual(metricsNegative.remainingPaise, 0);
  });
});

test('5. Current-Month Date Filtering', async (t) => {
  await t.test('filters expenses to only match the target reference month', () => {
    const refDate = new Date('2026-11-15T00:00:00Z');
    const expenses = [
      { id: '1', date: '2026-11-01', amountPaise: 10000 },
      { id: '2', date: '2026-11-14', amountPaise: 20000 },
      { id: '3', date: '2026-10-31', amountPaise: 30000 }, // previous month
      { id: '4', date: '2026-12-01', amountPaise: 40000 }, // next month
    ];

    const filtered = filterExpensesForCurrentMonth(expenses, refDate);
    assert.strictEqual(filtered.length, 2);
    assert.strictEqual(filtered[0].id, '1');
    assert.strictEqual(filtered[1].id, '2');
  });
});

test('6. Empty-State Detection & Mock Dataset Integrity', async (t) => {
  await t.test('accurately identifies empty dashboard datasets', () => {
    const emptyData = getMockEmptyDashboardData(new Date('2026-11-01'));
    assert.strictEqual(isDashboardEmpty(emptyData), true);
    assert.strictEqual(emptyData.recentExpenses.length, 0);
    assert.strictEqual(emptyData.totalSpentPaise, 0);
    assert.strictEqual(emptyData.budget.spentPaise, 0);
  });

  await t.test('populated mock dataset has valid non-zero values and dynamic dates', () => {
    const populated = getMockPopulatedDashboardData(new Date('2026-11-15'));
    assert.strictEqual(isDashboardEmpty(populated), false);
    assert.strictEqual(populated.recentExpenses.length, 3);
    assert.strictEqual(populated.totalSpentPaise, 450000);
    assert.strictEqual(populated.balances.youAreOwedPaise, 340000);
    assert.strictEqual(populated.balances.youOwePaise, 115000);
    assert.strictEqual(populated.balances.isProvisional, true);

    // Verify dates stay within November 2026
    populated.recentExpenses.forEach((exp) => {
      assert.ok(exp.date.startsWith('2026-11'), `Expense date ${exp.date} must be in reference month`);
    });
  });
});
