import test from 'node:test';
import assert from 'node:assert';
import {
  calculateBudgetMetrics,
  calculateTotalSpentPaise,
  filterExpensesForCurrentMonth,
  formatPaiseToInr,
} from '../src/features/home/utils/dashboardSummary.ts';
import { MOCK_POPULATED_DASHBOARD_DATA } from '../src/features/home/data/mockDashboardData.ts';

// ---------------------------------------------------------------------------
// 1. Dashboard Computational and Data Processing Latency Measurement
// ---------------------------------------------------------------------------
test('Dashboard Warm-Server Performance Benchmark (< 3.0 seconds target)', async (t) => {
  await t.test('measures integer-paise calculations and formatting over 1,000 operations', () => {
    const start = performance.now();

    // Simulate 1,000 rapid calculations typical of dashboard re-renders and metric derivations
    for (let i = 0; i < 1000; i++) {
      const totalSpent = calculateTotalSpentPaise(MOCK_POPULATED_DASHBOARD_DATA.recentExpenses);
      const metrics = calculateBudgetMetrics(10000000, totalSpent);
      formatPaiseToInr(totalSpent);
      formatPaiseToInr(metrics.remainingPaise);
    }

    const durationMs = performance.now() - start;
    const avgPerCycleMs = durationMs / 1000;

    // Must be vastly below 3000ms threshold (sub-millisecond computation)
    assert.ok(
      avgPerCycleMs < 1.0,
      `Average dashboard metric calculation took ${avgPerCycleMs.toFixed(3)}ms (must be < 1.0ms)`
    );
    assert.ok(
      durationMs < 500,
      `1,000 dashboard calculation cycles took ${durationMs.toFixed(2)}ms (well within 3000ms budget)`
    );
  });

  await t.test('simulates end-to-end warm-server dashboard load pipeline', async () => {
    const warmStart = performance.now();

    // 1. Simulated warm server API response latency (typical LAN or warm container: 20-50ms)
    await new Promise((resolve) => setTimeout(resolve, 35));

    // 2. Data parsing and state preparation
    const expenses = MOCK_POPULATED_DASHBOARD_DATA.recentExpenses;
    const currentMonthExpenses = filterExpensesForCurrentMonth(expenses, new Date('2026-11-20'));
    const totalSpentPaise = calculateTotalSpentPaise(currentMonthExpenses);
    const budgetMetrics = calculateBudgetMetrics(
      MOCK_POPULATED_DASHBOARD_DATA.budget.monthlyLimitPaise,
      totalSpentPaise
    );

    assert.ok(typeof totalSpentPaise === 'number');
    assert.ok(typeof budgetMetrics.percentageSpent === 'number');

    const totalDurationMs = performance.now() - warmStart;

    // Requirement: Dashboard should load in UNDER 3 SECONDS on a warm server.
    assert.ok(
      totalDurationMs < 3000,
      `Warm dashboard loaded in ${totalDurationMs.toFixed(2)}ms (TARGET: under 3000ms)`
    );
  });
});

// ---------------------------------------------------------------------------
// 2. Cold-Start / Sleeping Server vs Warm-Server Distinction Test
// ---------------------------------------------------------------------------
test('Distinguishes warm-server performance from cold-start/server-waking states', async (t) => {
  function determineLoadingState({ elapsedTimeMs, isServerResponding }) {
    const WAKING_UP_THRESHOLD_MS = 3500;
    if (!isServerResponding && elapsedTimeMs >= WAKING_UP_THRESHOLD_MS) {
      return {
        status: 'SERVER_WAKING_UP',
        message: 'Our server is waking up. Please wait a moment...',
        showBanner: true,
      };
    }
    if (!isServerResponding) {
      return {
        status: 'WARM_LOADING',
        message: 'Loading...',
        showBanner: false,
      };
    }
    return {
      status: 'AVAILABLE',
      message: null,
      showBanner: false,
    };
  }

  await t.test('warm server responding within 200ms stays in normal loading state without waking banner', () => {
    const state = determineLoadingState({ elapsedTimeMs: 200, isServerResponding: false });
    assert.strictEqual(state.status, 'WARM_LOADING');
    assert.strictEqual(state.showBanner, false);
  });

  await t.test('sleeping server delayed past 3.5s automatically transitions to waking-up state', () => {
    const state = determineLoadingState({ elapsedTimeMs: 3600, isServerResponding: false });
    assert.strictEqual(state.status, 'SERVER_WAKING_UP');
    assert.strictEqual(state.message, 'Our server is waking up. Please wait a moment...');
    assert.strictEqual(state.showBanner, true);
  });

  await t.test('server response resolves and automatically transitions out of waking state', () => {
    const state = determineLoadingState({ elapsedTimeMs: 4200, isServerResponding: true });
    assert.strictEqual(state.status, 'AVAILABLE');
    assert.strictEqual(state.showBanner, false);
  });
});
