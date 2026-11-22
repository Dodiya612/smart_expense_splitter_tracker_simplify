import test from 'node:test';
import assert from 'node:assert';
import { computeVirtualWindow } from '../src/components/ui/virtualizationUtils.ts';

// ---------------------------------------------------------------------------
// Helpers to generate realistic test datasets
// ---------------------------------------------------------------------------
function generateExpensesDataset(count) {
  const categories = ['food', 'transport', 'utilities', 'entertainment', 'shopping', 'health'];
  return Array.from({ length: count }, (_, i) => ({
    id: `expense-${i + 1}`,
    amountPaise: Math.floor(Math.random() * 500000) + 1000,
    categoryId: categories[i % categories.length],
    date: '2026-11-20',
    notes: `Transaction note #${i + 1}`,
    merchant: `Merchant ${(i % 20) + 1}`,
  }));
}

// ---------------------------------------------------------------------------
// 1. Virtualization Window Calculation with 100 Rows Dataset
// ---------------------------------------------------------------------------
test('VirtualizedList with 100 rows dataset', async (t) => {
  const count = 100;
  const itemHeight = 150;
  const viewportHeight = 800; // ~5-6 items visible on a standard phone or desktop view
  const overscan = 5;

  await t.test('initial top position (scrollTop = 0) renders bounded items', () => {
    const result = computeVirtualWindow({
      dataLength: count,
      itemHeight,
      scrollTop: 0,
      viewportHeight,
      overscan,
    });

    assert.strictEqual(result.startIndex, 0);
    // visible: ceil(800 / 150) = 6. With overscan 5: 0 + 6 + 5 = 11
    assert.strictEqual(result.endIndex, 11);
    assert.strictEqual(result.renderedCount, 11);
    assert.strictEqual(result.topSpacerHeight, 0);
    assert.strictEqual(result.bottomSpacerHeight, (100 - 11) * 150);
    assert.strictEqual(result.totalContentHeight, 100 * 150);

    // Sum invariant check
    const accountedHeight =
      result.topSpacerHeight + result.renderedCount * itemHeight + result.bottomSpacerHeight;
    assert.strictEqual(accountedHeight, result.totalContentHeight);
  });

  await t.test('mid-scroll position (scrollTop = 4,500) windows correctly', () => {
    const result = computeVirtualWindow({
      dataLength: count,
      itemHeight,
      scrollTop: 4500, // item index 30
      viewportHeight,
      overscan,
    });

    // rawStart = 30. With overscan: 30 - 5 = 25
    assert.strictEqual(result.startIndex, 25);
    // rawEnd = ceil(5300 / 150) = 36. With overscan: 36 + 5 = 41
    assert.strictEqual(result.endIndex, 41);
    assert.strictEqual(result.renderedCount, 16);
    assert.strictEqual(result.topSpacerHeight, 25 * 150);
    assert.strictEqual(result.bottomSpacerHeight, (100 - 41) * 150);

    const accountedHeight =
      result.topSpacerHeight + result.renderedCount * itemHeight + result.bottomSpacerHeight;
    assert.strictEqual(accountedHeight, result.totalContentHeight);
  });

  await t.test('bottom scroll position reaches the end without exceeding bounds', () => {
    const result = computeVirtualWindow({
      dataLength: count,
      itemHeight,
      scrollTop: 14200, // Near bottom
      viewportHeight,
      overscan,
    });

    assert.strictEqual(result.endIndex, 100);
    assert.strictEqual(result.bottomSpacerHeight, 0);
    assert.ok(result.startIndex > 0);
    assert.ok(result.topSpacerHeight > 0);
  });
});

// ---------------------------------------------------------------------------
// 2. Virtualization Window Calculation with 500 Rows Dataset
// ---------------------------------------------------------------------------
test('VirtualizedList with 500 rows dataset', async (t) => {
  const count = 500;
  const itemHeight = 150;
  const viewportHeight = 800;
  const overscan = 5;

  await t.test('at 500 rows only ~3% of items are in the DOM at initial render', () => {
    const result = computeVirtualWindow({
      dataLength: count,
      itemHeight,
      scrollTop: 0,
      viewportHeight,
      overscan,
    });

    assert.strictEqual(result.startIndex, 0);
    assert.strictEqual(result.endIndex, 11);
    assert.strictEqual(result.renderedCount, 11);
    // Only 11 of 500 items rendered in DOM
    assert.ok(result.renderedCount / count < 0.03);
    assert.strictEqual(result.totalContentHeight, 500 * 150); // 75,000 px
    assert.strictEqual(result.bottomSpacerHeight, (500 - 11) * 150);
  });

  await t.test('scrolling mid-way (scrollTop = 30,000) maintains strictly bounded DOM count', () => {
    const result = computeVirtualWindow({
      dataLength: count,
      itemHeight,
      scrollTop: 30000, // item index 200
      viewportHeight,
      overscan,
    });

    assert.strictEqual(result.startIndex, 195);
    assert.strictEqual(result.endIndex, 211);
    assert.strictEqual(result.renderedCount, 16);
    assert.strictEqual(result.topSpacerHeight, 195 * 150);
    assert.strictEqual(result.bottomSpacerHeight, (500 - 211) * 150);

    const accountedHeight =
      result.topSpacerHeight + result.renderedCount * itemHeight + result.bottomSpacerHeight;
    assert.strictEqual(accountedHeight, 75000);
  });
});

// ---------------------------------------------------------------------------
// 3. Virtualization Window Calculation with 1,000 Rows Dataset
// ---------------------------------------------------------------------------
test('VirtualizedList with 1,000 rows dataset', async (t) => {
  const count = 1000;
  const itemHeight = 150;
  const viewportHeight = 800;
  const overscan = 5;

  await t.test('at 1,000 rows only 1.1% of items are in the DOM at initial render', () => {
    const result = computeVirtualWindow({
      dataLength: count,
      itemHeight,
      scrollTop: 0,
      viewportHeight,
      overscan,
    });

    assert.strictEqual(result.startIndex, 0);
    assert.strictEqual(result.endIndex, 11);
    assert.strictEqual(result.renderedCount, 11);
    assert.ok(result.renderedCount / count <= 0.011);
    assert.strictEqual(result.totalContentHeight, 150000); // 150,000 px
  });

  await t.test('deep scroll (scrollTop = 75,000, 50% through 1,000 items)', () => {
    const result = computeVirtualWindow({
      dataLength: count,
      itemHeight,
      scrollTop: 75000,
      viewportHeight,
      overscan,
    });

    assert.strictEqual(result.startIndex, 495);
    assert.strictEqual(result.endIndex, 511);
    assert.strictEqual(result.renderedCount, 16);
    assert.strictEqual(result.topSpacerHeight, 495 * 150);
    assert.strictEqual(result.bottomSpacerHeight, (1000 - 511) * 150);

    const accountedHeight =
      result.topSpacerHeight + result.renderedCount * itemHeight + result.bottomSpacerHeight;
    assert.strictEqual(accountedHeight, 150000);
  });

  await t.test('end of 1,000 items list clamps safely at total count', () => {
    const result = computeVirtualWindow({
      dataLength: count,
      itemHeight,
      scrollTop: 149200,
      viewportHeight,
      overscan,
    });

    assert.strictEqual(result.endIndex, 1000);
    assert.strictEqual(result.bottomSpacerHeight, 0);
    assert.ok(result.renderedCount <= 16);
  });
});

// ---------------------------------------------------------------------------
// 4. Invariant and Performance Benchmark (60 FPS frame budget)
// ---------------------------------------------------------------------------
test('Virtualization mathematical invariants and frame budget performance', async (t) => {
  const itemHeight = 150;
  const viewportHeight = 800;
  const overscan = 5;

  await t.test('DOM node count is O(1) constant irrespective of dataset size', () => {
    const testSizes = [100, 500, 1000, 5000, 10000];
    const maxAllowedNodes = Math.ceil(viewportHeight / itemHeight) + 2 * overscan + 2;

    for (const size of testSizes) {
      const midScroll = (size * itemHeight) / 2;
      const result = computeVirtualWindow({
        dataLength: size,
        itemHeight,
        scrollTop: midScroll,
        viewportHeight,
        overscan,
      });

      assert.ok(
        result.renderedCount <= maxAllowedNodes,
        `Failed for size ${size}: renderedCount ${result.renderedCount} exceeds ${maxAllowedNodes}`
      );
    }
  });

  await t.test('computations for 1,000 rows complete in < 0.1ms (well within 16.6ms 60fps budget)', () => {
    const start = performance.now();
    for (let i = 0; i < 500; i++) {
      computeVirtualWindow({
        dataLength: 1000,
        itemHeight,
        scrollTop: i * 300,
        viewportHeight,
        overscan,
      });
    }
    const end = performance.now();
    const avgTimeMs = (end - start) / 500;

    assert.ok(avgTimeMs < 0.1, `Average time ${avgTimeMs.toFixed(4)}ms is under 0.1ms`);
  });
});

// ---------------------------------------------------------------------------
// 5. Search, Filter, and Deletion Preservation with 1,000 Rows
// ---------------------------------------------------------------------------
test('Data filtering and deletion preservation on 1,000 rows dataset', async (t) => {
  const dataset = generateExpensesDataset(1000);

  await t.test('filtering by category updates slice immediately without breaking virtualization', () => {
    const filtered = dataset.filter((item) => item.categoryId === 'food');
    assert.ok(filtered.length > 0 && filtered.length < 1000);

    const result = computeVirtualWindow({
      dataLength: filtered.length,
      itemHeight: 150,
      scrollTop: 0,
      viewportHeight: 800,
      overscan: 5,
    });

    assert.strictEqual(result.startIndex, 0);
    assert.ok(result.endIndex <= filtered.length);
    assert.strictEqual(result.totalContentHeight, filtered.length * 150);
  });

  await t.test('deleting an item decrements total count and re-computes spacers', () => {
    const deletedId = 'expense-50';
    const remaining = dataset.filter((item) => item.id !== deletedId);
    assert.strictEqual(remaining.length, 999);

    const result = computeVirtualWindow({
      dataLength: remaining.length,
      itemHeight: 150,
      scrollTop: 7500,
      viewportHeight: 800,
      overscan: 5,
    });

    assert.strictEqual(result.totalContentHeight, 999 * 150);
    const accountedHeight =
      result.topSpacerHeight + result.renderedCount * 150 + result.bottomSpacerHeight;
    assert.strictEqual(accountedHeight, 999 * 150);
  });
});
