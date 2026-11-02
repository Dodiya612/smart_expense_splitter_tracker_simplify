import test from 'node:test';
import assert from 'node:assert';

import { CATEGORIES } from '../src/features/expenses/types.ts';

// ---------------------------------------------------------------------------
// Pure logic matching ExpenseHistoryScreen list state and filtering
// ---------------------------------------------------------------------------

function applyLocalDeletionOverlay(backendExpenses, deletedIds, restoredItems) {
  const filteredBase = backendExpenses.filter((e) => !deletedIds.has(e.id));
  const combined = [...restoredItems, ...filteredBase];

  const seen = new Set();
  return combined.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function determineHistoryScreenState({
  isLoading,
  error,
  displayedCount,
  isFiltered,
}) {
  if (isLoading && displayedCount === 0) {
    return 'INITIAL_LOADING';
  }
  if (error && displayedCount === 0) {
    return 'INITIAL_ERROR';
  }
  if (displayedCount === 0) {
    return isFiltered ? 'NO_RESULTS' : 'EMPTY';
  }
  return 'POPULATED';
}

function matchesFilter(expense, { categoryId, query }) {
  if (categoryId && expense.categoryId !== categoryId) {
    return false;
  }
  if (query && query.trim()) {
    const q = query.trim().toLowerCase();
    const notes = (expense.notes || '').toLowerCase();
    const description = (expense.description || '').toLowerCase();
    const merchant = (expense.merchant || '').toLowerCase();
    return notes.includes(q) || description.includes(q) || merchant.includes(q);
  }
  return true;
}

// ---------------------------------------------------------------------------
// 1. Local Deletion and Undo Overlay Tests (T-20 / US-08 compliance)
// ---------------------------------------------------------------------------
test('ExpenseHistoryScreen local deletion and undo overlay', async (t) => {
  const sampleItems = [
    { id: 'exp-1', amountPaise: 10000, categoryId: 'food', date: '2026-10-31' },
    { id: 'exp-2', amountPaise: 25000, categoryId: 'transport', date: '2026-10-31' },
    { id: 'exp-3', amountPaise: 50000, categoryId: 'utilities', date: '2026-10-30' },
  ];

  await t.test('deleting an item immediately removes it from displayed list', () => {
    const deletedIds = new Set(['exp-2']);
    const displayed = applyLocalDeletionOverlay(sampleItems, deletedIds, []);

    assert.strictEqual(displayed.length, 2);
    assert.strictEqual(displayed[0].id, 'exp-1');
    assert.strictEqual(displayed[1].id, 'exp-3');
    assert.strictEqual(displayed.find((e) => e.id === 'exp-2'), undefined);
  });

  await t.test('undoing deletion restores item and deduplicates ID', () => {
    const deletedIds = new Set();
    const restored = [{ id: 'exp-2', amountPaise: 25000, categoryId: 'transport', date: '2026-10-31' }];

    const displayed = applyLocalDeletionOverlay(sampleItems, deletedIds, restored);

    assert.strictEqual(displayed.length, 3);
    assert.strictEqual(displayed[0].id, 'exp-2'); // Restored item prepended
    // ID deduplication prevents duplicates
    const exp2Count = displayed.filter((e) => e.id === 'exp-2').length;
    assert.strictEqual(exp2Count, 1);
  });
});

// ---------------------------------------------------------------------------
// 2. Screen Lifecycle State Determination Tests
// ---------------------------------------------------------------------------
test('ExpenseHistoryScreen state determination', async (t) => {
  await t.test('detects initial loading state', () => {
    const state = determineHistoryScreenState({
      isLoading: true,
      error: null,
      displayedCount: 0,
      isFiltered: false,
    });
    assert.strictEqual(state, 'INITIAL_LOADING');
  });

  await t.test('detects initial error state', () => {
    const state = determineHistoryScreenState({
      isLoading: false,
      error: new Error('Network error'),
      displayedCount: 0,
      isFiltered: false,
    });
    assert.strictEqual(state, 'INITIAL_ERROR');
  });

  await t.test('detects true empty state when no filters are active', () => {
    const state = determineHistoryScreenState({
      isLoading: false,
      error: null,
      displayedCount: 0,
      isFiltered: false,
    });
    assert.strictEqual(state, 'EMPTY');
  });

  await t.test('detects no-results state when filters are active', () => {
    const state = determineHistoryScreenState({
      isLoading: false,
      error: null,
      displayedCount: 0,
      isFiltered: true,
    });
    assert.strictEqual(state, 'NO_RESULTS');
  });

  await t.test('detects populated list state', () => {
    const state = determineHistoryScreenState({
      isLoading: false,
      error: null,
      displayedCount: 5,
      isFiltered: false,
    });
    assert.strictEqual(state, 'POPULATED');
  });
});

// ---------------------------------------------------------------------------
// 3. Search and Category Filter Matching Tests
// ---------------------------------------------------------------------------
test('ExpenseHistoryScreen filter matching integrity', async (t) => {
  const item = {
    id: 'exp-10',
    amountPaise: 35000,
    categoryId: 'food',
    notes: 'Dinner at Pizza Express',
    description: 'Pizza meal',
    merchant: 'Pizza Express',
  };

  await t.test('matches exact category filter', () => {
    assert.strictEqual(matchesFilter(item, { categoryId: 'food' }), true);
    assert.strictEqual(matchesFilter(item, { categoryId: 'transport' }), false);
  });

  await t.test('matches search query across notes and merchant case-insensitively', () => {
    assert.strictEqual(matchesFilter(item, { query: 'pizza' }), true);
    assert.strictEqual(matchesFilter(item, { query: 'EXPRESS' }), true);
    assert.strictEqual(matchesFilter(item, { query: 'Dinner' }), true);
    assert.strictEqual(matchesFilter(item, { query: 'Uber' }), false);
  });

  await t.test('matches combined category and search filter', () => {
    assert.strictEqual(matchesFilter(item, { categoryId: 'food', query: 'Pizza' }), true);
    assert.strictEqual(matchesFilter(item, { categoryId: 'utilities', query: 'Pizza' }), false);
  });

  await t.test('passes everything when no filters are applied', () => {
    assert.strictEqual(matchesFilter(item, {}), true);
    assert.strictEqual(matchesFilter(item, { query: '   ' }), true);
  });
});

// ---------------------------------------------------------------------------
// 4. Category Constants Integrity for Filters
// ---------------------------------------------------------------------------
test('Category constants for history screen filters', async (t) => {
  await t.test('all CATEGORIES have non-empty IDs, labels, and palette indices', () => {
    assert.ok(CATEGORIES.length >= 8);
    for (const cat of CATEGORIES) {
      assert.strictEqual(typeof cat.id, 'string');
      assert.ok(cat.id.length > 0);
      assert.strictEqual(typeof cat.label, 'string');
      assert.ok(cat.label.length > 0);
      assert.strictEqual(typeof cat.paletteIndex, 'number');
      assert.ok(cat.paletteIndex >= 0);
    }
  });
});