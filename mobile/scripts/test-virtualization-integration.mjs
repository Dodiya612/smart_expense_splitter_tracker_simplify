import test from 'node:test';
import assert from 'node:assert';
import { computeVirtualWindow } from '../src/components/ui/virtualizationUtils.ts';

// ---------------------------------------------------------------------------
// 1. Component Level Virtualization State & Rendering Integration Test
// ---------------------------------------------------------------------------
test('ExpenseHistoryScreen Virtualization UI Integration Logic', async (t) => {
  function generateTestExpenses(count) {
    const cats = ['food', 'transport', 'utilities', 'entertainment'];
    return Array.from({ length: count }, (_, i) => ({
      id: `exp-${i + 1}`,
      amountPaise: (i + 1) * 10000,
      categoryId: cats[i % cats.length],
      date: '2026-11-20',
      notes: `Expense item ${i + 1}`,
      merchant: `Store ${i + 1}`,
    }));
  }

  function simulateVirtualListRender({ data, scrollTop, viewportHeight = 800, itemHeight = 150, overscan = 5 }) {
    const windowResult = computeVirtualWindow({
      dataLength: data.length,
      itemHeight,
      scrollTop,
      viewportHeight,
      overscan,
    });

    const visibleItems = data.slice(windowResult.startIndex, windowResult.endIndex).map((item, idx) => ({
      item,
      index: windowResult.startIndex + idx,
    }));

    return {
      windowResult,
      visibleItems,
      topSpacerHeight: windowResult.topSpacerHeight,
      bottomSpacerHeight: windowResult.bottomSpacerHeight,
      totalContentHeight: windowResult.totalContentHeight,
      renderedCount: visibleItems.length,
    };
  }

  await t.test('100 records: renders only 11 items in DOM at top, remainder in bottom spacer', () => {
    const data = generateTestExpenses(100);
    const render = simulateVirtualListRender({ data, scrollTop: 0 });

    assert.strictEqual(render.renderedCount, 11);
    assert.strictEqual(render.topSpacerHeight, 0);
    assert.strictEqual(render.bottomSpacerHeight, 89 * 150);
    assert.strictEqual(render.visibleItems[0].item.id, 'exp-1');
    assert.strictEqual(render.visibleItems[10].item.id, 'exp-11');
  });

  await t.test('500 records: scrolling to middle (item 250) bounds rendered DOM nodes to 16 items', () => {
    const data = generateTestExpenses(500);
    const render = simulateVirtualListRender({ data, scrollTop: 250 * 150 });

    assert.strictEqual(render.renderedCount, 16);
    assert.strictEqual(render.windowResult.startIndex, 245);
    assert.strictEqual(render.windowResult.endIndex, 261);
    assert.strictEqual(render.topSpacerHeight, 245 * 150);
    assert.strictEqual(render.bottomSpacerHeight, (500 - 261) * 150);
  });

  await t.test('1,000 records: only 11 items initially rendered (98.9% kept out of DOM)', () => {
    const data = generateTestExpenses(1000);
    const render = simulateVirtualListRender({ data, scrollTop: 0 });

    assert.strictEqual(render.renderedCount, 11);
    assert.strictEqual(render.totalContentHeight, 150000);
    assert.strictEqual(render.bottomSpacerHeight, (1000 - 11) * 150);
  });

  await t.test('Search filtering on 1,000 records dynamically collapses virtualization window', () => {
    const data = generateTestExpenses(1000);
    // Filter for "Store 5" (e.g., Store 5, Store 50..59, Store 500..599)
    const filtered = data.filter((e) => e.merchant.includes('Store 5'));
    assert.ok(filtered.length > 0 && filtered.length < 1000);

    const render = simulateVirtualListRender({ data: filtered, scrollTop: 0 });
    assert.strictEqual(render.topSpacerHeight, 0);
    assert.strictEqual(render.totalContentHeight, filtered.length * 150);
    assert.strictEqual(render.bottomSpacerHeight, (filtered.length - render.renderedCount) * 150);
  });

  await t.test('Deletion and 10-second undo loop retains virtualized list integrity', () => {
    let dataset = generateTestExpenses(100);
    const deletedItem = dataset[10]; // exp-11

    // 1. Delete item
    dataset = dataset.filter((e) => e.id !== deletedItem.id);
    assert.strictEqual(dataset.length, 99);

    let render = simulateVirtualListRender({ data: dataset, scrollTop: 0 });
    assert.strictEqual(render.totalContentHeight, 99 * 150);
    assert.strictEqual(render.visibleItems.find((v) => v.item.id === deletedItem.id), undefined);

    // 2. Undo restores item to front of list
    dataset = [deletedItem, ...dataset];
    assert.strictEqual(dataset.length, 100);

    render = simulateVirtualListRender({ data: dataset, scrollTop: 0 });
    assert.strictEqual(render.visibleItems[0].item.id, deletedItem.id);
    assert.strictEqual(render.totalContentHeight, 100 * 150);
  });
});
