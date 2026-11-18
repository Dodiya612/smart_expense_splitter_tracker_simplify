import test from 'node:test';
import assert from 'node:assert';
import { formatPaise, parseRupeesToPaise, paiseToInputText } from '../src/utils/money.ts';
import {
  allocateByWeights,
  allocateEqual,
  basisPointsToPercentText,
  buildSplitPreview,
  parseParts,
  parsePercentToBasisPoints,
  toSplitWeights,
} from '../src/utils/splits.ts';
import {
  canSave,
  groupExpenseErrorMessage,
  toCreateBody,
  todayInKolkata,
  validateGroupExpense,
} from '../src/features/groups/utils/groupExpenseForm.ts';
import { splitSummaryText } from '../src/features/groups/utils/splitSummary.ts';

const ABC = ['alex', 'blair', 'casey'];

test('T-31 / US-19: worked examples from ledger.md match the backend tests', () => {
  assert.deepStrictEqual(allocateEqual(300000, ABC), { alex: 100000, blair: 100000, casey: 100000 });
  // Chai: the leftover paisa goes to the first person in order.
  assert.deepStrictEqual(allocateEqual(10000, ABC), { alex: 3334, blair: 3333, casey: 3333 });
  // 50/25/25 of ₹55.55: the two largest remainders get the leftover paise.
  assert.deepStrictEqual(allocateByWeights(5555, ABC, [5000, 2500, 2500]), { alex: 2777, blair: 1389, casey: 1389 });
  // Parts 3:2:2 of ₹100.
  assert.deepStrictEqual(allocateByWeights(10000, ABC, [3, 2, 2]), { alex: 4286, blair: 2857, casey: 2857 });
});

test('T-31 / US-19: property — 10,000 random splits always add up exactly', () => {
  let seed = 7;
  const rnd = (n) => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed % n;
  };
  for (let i = 0; i < 10000; i++) {
    const n = 1 + rnd(10);
    const ids = Array.from({ length: n }, (_, k) => `u${k}`);
    const total = 1 + rnd(1_000_000_000);
    const weights = ids.map(() => 1 + rnd(1000));
    const shares = allocateByWeights(total, ids, weights);
    const values = Object.values(shares);
    assert.strictEqual(values.reduce((a, b) => a + b, 0), total, `case ${i}`);
    const wSum = weights.reduce((a, b) => a + b, 0);
    ids.forEach((id, k) => {
      const floor = Math.floor((total * weights[k]) / wSum);
      assert.ok(shares[id] === floor || shares[id] === floor + 1, `case ${i}: share off by more than 1 paisa`);
      assert.ok(Number.isInteger(shares[id]));
    });
  }
});

test('T-31: money parsing never uses floats', () => {
  assert.strictEqual(parseRupeesToPaise('250'), 25000);
  assert.strictEqual(parseRupeesToPaise('250.5'), 25050);
  assert.strictEqual(parseRupeesToPaise('0.10'), 10);
  assert.strictEqual(parseRupeesToPaise('1,250.75'), 125075);
  assert.strictEqual(parseRupeesToPaise('12.'), 1200);
  assert.strictEqual(parseRupeesToPaise('1.234'), null);
  assert.strictEqual(parseRupeesToPaise('-5'), null);
  assert.strictEqual(parseRupeesToPaise('abc'), null);
  assert.strictEqual(parseRupeesToPaise(''), null);
  assert.strictEqual(formatPaise(123456), '₹1,234.56');
  assert.strictEqual(formatPaise(-5), '-₹0.05');
  assert.strictEqual(paiseToInputText(123450), '1234.50');
});

test('T-31: percent and parts parsing', () => {
  assert.strictEqual(parsePercentToBasisPoints('33.33'), 3333);
  assert.strictEqual(parsePercentToBasisPoints('50'), 5000);
  assert.strictEqual(parsePercentToBasisPoints('100'), 10000);
  assert.strictEqual(parsePercentToBasisPoints('100.01'), null);
  assert.strictEqual(parsePercentToBasisPoints('1.234'), null);
  assert.strictEqual(basisPointsToPercentText(3333), '33.33');
  assert.strictEqual(basisPointsToPercentText(500), '5.00');
  assert.strictEqual(parseParts('2'), 2);
  assert.strictEqual(parseParts('0'), null);
  assert.strictEqual(parseParts('1.5'), null);
  assert.strictEqual(parseParts('1001'), null);
});

test('T-31: live preview — exact mode shows what is left or too much', () => {
  const base = { mode: 'exact', totalPaise: 15000, participantIds: ABC };
  const short = buildSplitPreview({ ...base, values: { alex: '60', blair: '50', casey: '30' } });
  assert.strictEqual(short.remainingPaise, 1000);
  assert.strictEqual(short.isBalanced, false);
  assert.strictEqual(splitSummaryText('exact', short), '₹10.00 left to assign.');
  const over = buildSplitPreview({ ...base, values: { alex: '60', blair: '50', casey: '50' } });
  assert.strictEqual(over.remainingPaise, -1000);
  assert.match(splitSummaryText('exact', over), /₹10.00 too much/);
  const ok = buildSplitPreview({ ...base, values: { alex: '60', blair: '50', casey: '40' } });
  assert.ok(ok.isBalanced);
  assert.deepStrictEqual(ok.shares, { alex: 6000, blair: 5000, casey: 4000 });
  const bad = buildSplitPreview({ ...base, values: { alex: '60', blair: 'x', casey: '' } });
  assert.ok(bad.fieldErrors.blair && bad.fieldErrors.casey);
  assert.strictEqual(bad.isBalanced, false);
});

test('T-31: live preview — percentages must reach exactly 100.00', () => {
  const base = { mode: 'percentage', totalPaise: 10000, participantIds: ABC };
  const short = buildSplitPreview({ ...base, values: { alex: '33.33', blair: '33.33', casey: '33.33' } });
  assert.strictEqual(short.isBalanced, false);
  assert.strictEqual(short.remainingBasisPoints, 1);
  assert.strictEqual(splitSummaryText('percentage', short), '0.01% left to assign.');
  const ok = buildSplitPreview({ ...base, values: { alex: '33.34', blair: '33.33', casey: '33.33' } });
  assert.ok(ok.isBalanced);
  assert.strictEqual(Object.values(ok.shares).reduce((a, b) => a + b, 0), 10000);
});

test('T-31: live preview — parts and equal, plus empty states', () => {
  const parts = buildSplitPreview({ mode: 'parts', totalPaise: 10000, participantIds: ABC, values: { alex: '3', blair: '2', casey: '2' } });
  assert.deepStrictEqual(parts.shares, { alex: 4286, blair: 2857, casey: 2857 });
  const zeroPart = buildSplitPreview({ mode: 'parts', totalPaise: 10000, participantIds: ABC, values: { alex: '0', blair: '2', casey: '2' } });
  assert.strictEqual(zeroPart.isBalanced, false);
  const nobody = buildSplitPreview({ mode: 'equal', totalPaise: 10000, participantIds: [], values: {} });
  assert.strictEqual(nobody.isBalanced, false);
  assert.match(nobody.problem, /at least one person/);
  const noAmount = buildSplitPreview({ mode: 'equal', totalPaise: null, participantIds: ABC, values: {} });
  assert.strictEqual(noAmount.isBalanced, false);
});

function form(overrides = {}) {
  return {
    amountText: '150',
    description: 'Dinner',
    categoryId: '00000000-0000-4000-8000-000000000001',
    payerId: 'alex',
    notes: '',
    mode: 'exact',
    participantIds: ABC,
    splitValues: { equal: {}, exact: { alex: '60', blair: '50', casey: '40' }, percentage: {}, parts: {} },
    ...overrides,
  };
}

test('T-31 Done when: an unbalanced split cannot be saved', () => {
  assert.strictEqual(canSave(form()), true);
  const unbalanced = form({ splitValues: { equal: {}, exact: { alex: '60', blair: '50', casey: '30' }, percentage: {}, parts: {} } });
  assert.strictEqual(canSave(unbalanced), false);
  assert.strictEqual(canSave(form({ mode: 'percentage', splitValues: { equal: {}, exact: {}, percentage: { alex: '50', blair: '25', casey: '24.99' }, parts: {} } })), false);
  assert.strictEqual(canSave(form({ participantIds: [] , mode: 'equal' })), false);
  assert.strictEqual(canSave(form({ description: '  ' })), false);
  assert.ok(validateGroupExpense(form({ amountText: '0' })).amountText);
  assert.ok(validateGroupExpense(form({ categoryId: null })).categoryId);
});

test('T-31: request body matches the T-30 API', () => {
  const body = toCreateBody(form(), '2026-11-18');
  assert.deepStrictEqual(body, {
    amount_paise: 15000,
    description: 'Dinner',
    category_id: '00000000-0000-4000-8000-000000000001',
    expense_date: '2026-11-18',
    paid_by_user_id: 'alex',
    participant_user_ids: ABC,
    split_mode: 'exact',
    split_weights: { alex: 6000, blair: 5000, casey: 4000 },
    notes: undefined,
  });
  assert.deepStrictEqual(
    toSplitWeights('percentage', ABC, { alex: '50', blair: '25', casey: '25.5' }),
    { alex: '50.00', blair: '25.00', casey: '25.50' }
  );
  assert.strictEqual(toSplitWeights('equal', ABC, {}), undefined);
});

test('T-31: dates use Asia/Kolkata and errors read plainly', () => {
  assert.strictEqual(todayInKolkata(new Date('2026-11-18T20:00:00Z')), '2026-11-19');
  assert.strictEqual(todayInKolkata(new Date('2026-11-18T18:00:00Z')), '2026-11-18');
  assert.match(groupExpenseErrorMessage('UNBALANCED_SHARES', 'x'), /does not add up/);
  assert.strictEqual(groupExpenseErrorMessage('NETWORK_ERROR', 'No connection'), 'No connection');
});
