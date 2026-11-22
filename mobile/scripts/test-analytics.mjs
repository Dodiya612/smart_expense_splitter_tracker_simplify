import test from 'node:test';
import assert from 'node:assert';
import {
  mapSummary,
  mapTrends,
  mapCategories,
} from '../src/features/analytics/services/analyticsApi.ts';
import {
  computePresetRange,
  formatDateKolkata,
  validateDateRange,
  isValidDateFormat,
} from '../src/features/analytics/utils/dateRange.ts';

test('T-43 / US-12: Spending Analytics & Charts Test Suite', async (t) => {
  // Demo Dataset:
  // 1. Alex pays ₹3,000 groceries split 3 ways -> Alex share ₹1,000.00 (100,000p), cash paid ₹3,000.00 (300,000p)
  // 2. Blair repays Alex ₹1,000 (settlement) -> Spending / cash paid unchanged
  // 3. Alex adds ₹500 metro personal -> Alex share ₹1,500.00 (150,000p), cash paid ₹3,500.00 (350,000p)
  // 4. Casey pays ₹100 chai split 3 ways -> Alex share ₹1,533.34 (153,334p), cash paid ₹3,500.00 (350,000p)
  const demoSummaryRaw = {
    from_date: '2026-11-01',
    to_date: '2026-11-20',
    timezone: 'Asia/Kolkata',
    group_id: null,
    share_paise: 153334,
    cash_paid_paise: 350000,
    expense_count: 3,
    owed_to_you_paise: 200000,
    you_owe_paise: 0,
  };

  const demoTrendsRaw = {
    from_date: '2026-11-16',
    to_date: '2026-11-18',
    timezone: 'Asia/Kolkata',
    group_id: null,
    granularity: 'day',
    buckets: [
      {
        bucket_start: '2026-11-16',
        bucket_end: '2026-11-16',
        share_paise: 100000,
        cash_paid_paise: 300000,
        cumulative_share_paise: 100000,
        cumulative_cash_paid_paise: 300000,
      },
      {
        bucket_start: '2026-11-17',
        bucket_end: '2026-11-17',
        share_paise: 50000,
        cash_paid_paise: 50000,
        cumulative_share_paise: 150000,
        cumulative_cash_paid_paise: 350000,
      },
      {
        bucket_start: '2026-11-18',
        bucket_end: '2026-11-18',
        share_paise: 3334,
        cash_paid_paise: 0,
        cumulative_share_paise: 153334,
        cumulative_cash_paid_paise: 350000,
      },
    ],
    total_share_paise: 153334,
    total_cash_paid_paise: 350000,
  };

  const demoCategoriesRaw = {
    from_date: '2026-11-01',
    to_date: '2026-11-20',
    timezone: 'Asia/Kolkata',
    group_id: null,
    categories: [
      {
        category_id: '00000000-0000-4000-8000-000000000002',
        category_name: 'Groceries',
        share_paise: 100000,
        cash_paid_paise: 300000,
        expense_count: 1,
      },
      {
        category_id: '00000000-0000-4000-8000-000000000003',
        category_name: 'Travel',
        share_paise: 50000,
        cash_paid_paise: 50000,
        expense_count: 1,
      },
      {
        category_id: '00000000-0000-4000-8000-000000000001',
        category_name: 'Food & Dining',
        share_paise: 3334,
        cash_paid_paise: 0,
        expense_count: 1,
      },
    ],
    total_share_paise: 153334,
    total_cash_paid_paise: 350000,
  };

  await t.test('1. Summary response mapping matches DR-14 & CF-17 rules', () => {
    const summary = mapSummary(demoSummaryRaw);
    assert.strictEqual(summary.fromDate, '2026-11-01');
    assert.strictEqual(summary.toDate, '2026-11-20');
    assert.strictEqual(summary.sharePaise, 153334);
    assert.strictEqual(summary.cashPaidPaise, 350000);
    assert.strictEqual(summary.expenseCount, 3);
    assert.strictEqual(summary.owedToYouPaise, 200000);
    assert.strictEqual(summary.youOwePaise, 0);
  });

  await t.test('2. Trends response mapping and cumulative totals', () => {
    const trends = mapTrends(demoTrendsRaw);
    assert.strictEqual(trends.granularity, 'day');
    assert.strictEqual(trends.buckets.length, 3);
    assert.strictEqual(trends.totalSharePaise, 153334);
    assert.strictEqual(trends.totalCashPaidPaise, 350000);

    const b1 = trends.buckets[0];
    assert.strictEqual(b1.bucketStart, '2026-11-16');
    assert.strictEqual(b1.sharePaise, 100000);
    assert.strictEqual(b1.cashPaidPaise, 300000);
    assert.strictEqual(b1.cumulativeSharePaise, 100000);
    assert.strictEqual(b1.cumulativeCashPaidPaise, 300000);

    const b3 = trends.buckets[2];
    assert.strictEqual(b3.bucketStart, '2026-11-18');
    assert.strictEqual(b3.sharePaise, 3334);
    assert.strictEqual(b3.cashPaidPaise, 0);
    assert.strictEqual(b3.cumulativeSharePaise, 153334);
    assert.strictEqual(b3.cumulativeCashPaidPaise, 350000);
  });

  await t.test('3. Categories response mapping and sorting', () => {
    const categories = mapCategories(demoCategoriesRaw);
    assert.strictEqual(categories.categories.length, 3);
    assert.strictEqual(categories.totalSharePaise, 153334);
    assert.strictEqual(categories.totalCashPaidPaise, 350000);

    const topCategory = categories.categories[0];
    assert.strictEqual(topCategory.categoryName, 'Groceries');
    assert.strictEqual(topCategory.sharePaise, 100000);
    assert.strictEqual(topCategory.cashPaidPaise, 300000);
  });

  await t.test('4. Date range presets computation in Asia/Kolkata', () => {
    const testNow = new Date('2026-11-20T10:00:00Z');
    const range1M = computePresetRange('1M', testNow);
    assert.strictEqual(range1M.from, '2026-11-01');
    assert.strictEqual(range1M.to, '2026-11-20');

    const range3M = computePresetRange('3M', testNow);
    assert.strictEqual(range3M.from, '2026-09-01');
    assert.strictEqual(range3M.to, '2026-11-20');

    const range6M = computePresetRange('6M', testNow);
    assert.strictEqual(range6M.from, '2026-06-01');
    assert.strictEqual(range6M.to, '2026-11-20');

    const range1Y = computePresetRange('1Y', testNow);
    assert.strictEqual(range1Y.from, '2025-11-01');
    assert.strictEqual(range1Y.to, '2026-11-20');
  });

  await t.test('5. Safe fallback on empty responses', () => {
    const emptySummary = mapSummary({
      from_date: '2026-11-01',
      to_date: '2026-11-20',
      share_paise: 0,
      cash_paid_paise: 0,
      expense_count: 0,
      owed_to_you_paise: 0,
      you_owe_paise: 0,
    });
    assert.strictEqual(emptySummary.sharePaise, 0);
    assert.strictEqual(emptySummary.expenseCount, 0);

    const emptyTrends = mapTrends({
      from_date: '2026-11-01',
      to_date: '2026-11-20',
      granularity: 'day',
      buckets: [],
      total_share_paise: 0,
      total_cash_paid_paise: 0,
    });
    assert.strictEqual(emptyTrends.buckets.length, 0);
    assert.strictEqual(emptyTrends.totalSharePaise, 0);

    const emptyCategories = mapCategories({
      from_date: '2026-11-01',
      to_date: '2026-11-20',
      categories: [],
      total_share_paise: 0,
      total_cash_paid_paise: 0,
    });
    assert.strictEqual(emptyCategories.categories.length, 0);
    assert.strictEqual(emptyCategories.totalSharePaise, 0);
  });

  await t.test('6. Custom date range validation and boundaries', () => {
    // 6a. Valid format check
    assert.strictEqual(isValidDateFormat('2026-11-20'), true);
    assert.strictEqual(isValidDateFormat('2026-02-28'), true);
    assert.strictEqual(isValidDateFormat('2024-02-29'), true); // leap year
    assert.strictEqual(isValidDateFormat('2025-02-29'), false); // non-leap year
    assert.strictEqual(isValidDateFormat('20-11-2026'), false);
    assert.strictEqual(isValidDateFormat('2026/11/20'), false);
    assert.strictEqual(isValidDateFormat(''), false);
    assert.strictEqual(isValidDateFormat('not-a-date'), false);

    // 6b. Valid standard range
    const validRange = validateDateRange('2026-10-01', '2026-11-20');
    assert.strictEqual(validRange.isValid, true);
    assert.strictEqual(validRange.error, undefined);

    // 6c. Single day valid range (from === to)
    const singleDayRange = validateDateRange('2026-11-20', '2026-11-20');
    assert.strictEqual(singleDayRange.isValid, true);

    // 6d. Inverted date range (start after end)
    const invertedRange = validateDateRange('2026-11-20', '2026-10-01');
    assert.strictEqual(invertedRange.isValid, false);
    assert.strictEqual(invertedRange.error, 'Start date cannot be after end date.');

    // 6e. Malformed start date
    const malformedStart = validateDateRange('invalid-start', '2026-11-20');
    assert.strictEqual(malformedStart.isValid, false);
    assert.strictEqual(malformedStart.error, 'Start date must be in YYYY-MM-DD format.');

    // 6f. Malformed end date
    const malformedEnd = validateDateRange('2026-10-01', 'invalid-end');
    assert.strictEqual(malformedEnd.isValid, false);
    assert.strictEqual(malformedEnd.error, 'End date must be in YYYY-MM-DD format.');

    // 6g. Exceeding max 731 days limit (2 years)
    const overTwoYears = validateDateRange('2024-01-01', '2026-12-31');
    assert.strictEqual(overTwoYears.isValid, false);
    assert.strictEqual(overTwoYears.error, 'Date range cannot exceed 2 years (731 days).');

    // 6h. Exactly within 731 days limit
    const withinTwoYears = validateDateRange('2025-01-01', '2026-11-20');
    assert.strictEqual(withinTwoYears.isValid, true);
  });
});
