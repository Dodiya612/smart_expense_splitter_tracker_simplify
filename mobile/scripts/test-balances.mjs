import test from 'node:test';
import assert from 'node:assert';
import {
  mapGroupBalances,
  mapSettlement,
  mapSettlementList,
  mapSimplifiedRepayments,
} from '../src/features/balances/utils/parseBalances.ts';
import {
  deriveStandings,
  hasNoBalances,
  myPositionLabel,
  peerLabel,
  settlementLabel,
} from '../src/features/balances/utils/balanceLabels.ts';
import {
  buildSettlementPayload,
  checkSettlementAmount,
  createSettlementKeyTracker,
  runSettlement,
  SETTLE_FAILED_MESSAGE,
} from '../src/features/balances/utils/settlementSubmission.ts';
import {
  MOCK_ALEX,
  MOCK_BLAIR,
  MOCK_CASEY,
  mockBalancesGet,
  mockBalancesPost,
  resetMockBalances,
} from '../src/services/mock/mockBalances.ts';
import { ApiError } from '../src/services/api/types.ts';

// Real response shapes from backend/openapi.json (T-32), snake_case.
// Demo dataset (PRODUCT.md section 05 / ledger.md): Alex pays ₹3,000 (300,000 paise)
// for groceries split equally with Blair and Casey (₹1,000 each).
const ALEX = 'user-alex';
const BLAIR = 'user-blair';
const CASEY = 'user-casey';
const MEMBERS = [
  { userId: ALEX, name: 'Alex' },
  { userId: BLAIR, name: 'Blair' },
  { userId: CASEY, name: 'Casey' },
];

const demoBalances = {
  group_id: 'group-demo-01',
  net_positions: { [ALEX]: 200000, [BLAIR]: -100000, [CASEY]: -100000 },
  suggested_transfers: [
    { from_user: BLAIR, to_user: ALEX, amount_paise: 100000 },
    { from_user: CASEY, to_user: ALEX, amount_paise: 100000 },
  ],
  members: [
    { user_id: ALEX, net_balance_paise: 200000, owes_paise: 0, receives_paise: 200000, status: 'creditor' },
    { user_id: BLAIR, net_balance_paise: -100000, owes_paise: 100000, receives_paise: 0, status: 'debtor' },
    { user_id: CASEY, net_balance_paise: -100000, owes_paise: 100000, receives_paise: 0, status: 'debtor' },
  ],
  total_debt_paise: 200000,
  currency: 'INR',
};

const demoSimplified = {
  group_id: 'group-demo-01',
  suggested_transfers: demoBalances.suggested_transfers,
  total_transfers: 2,
  total_amount_paise: 200000,
};

// After Blair records a ₹1,000 settlement with Alex.
const afterBlairSettles = {
  group_id: 'group-demo-01',
  net_positions: { [ALEX]: 100000, [BLAIR]: 0, [CASEY]: -100000 },
  suggested_transfers: [{ from_user: CASEY, to_user: ALEX, amount_paise: 100000 }],
  members: [
    { user_id: ALEX, net_balance_paise: 100000, owes_paise: 0, receives_paise: 100000, status: 'creditor' },
    { user_id: BLAIR, net_balance_paise: 0, owes_paise: 0, receives_paise: 0, status: 'settled' },
    { user_id: CASEY, net_balance_paise: -100000, owes_paise: 100000, receives_paise: 0, status: 'debtor' },
  ],
  total_debt_paise: 100000,
  currency: 'INR',
};

const settlementResponse = {
  id: 'stl-1',
  group_id: 'group-demo-01',
  payer_id: BLAIR,
  payee_id: ALEX,
  amount_paise: 100000,
  status: 'completed',
  payment_method: 'upi',
  notes: null,
  settlement_date: '2026-11-19',
  is_partial: false,
  remaining_debt_paise: 0,
  created_at: '2026-11-19T10:00:00Z',
  updated_at: '2026-11-19T10:00:00Z',
};

function standingsFor(userId, raw = demoBalances) {
  const balances = mapGroupBalances(raw);
  return deriveStandings({
    currentUserId: userId,
    netPositions: balances.netPositions,
    transfers: balances.suggestedTransfers,
    members: MEMBERS,
  });
}

function keyFactory() {
  let n = 0;
  return () => `key-${++n}`;
}

test('T-33 / US-10: Group Balances & Settle Up Tests', async (t) => {
  await t.test('1. Definition of Done: Alex is correctly shown as owed ₹2,000 (200,000 paise)', () => {
    const groupBalances = mapGroupBalances(demoBalances);
    assert.strictEqual(groupBalances.groupId, 'group-demo-01');
    assert.strictEqual(groupBalances.currency, 'INR');
    assert.strictEqual(groupBalances.members.length, 3);
    assert.strictEqual(groupBalances.totalDebtPaise, 200000);

    const alex = groupBalances.members.find((m) => m.userId === ALEX);
    assert.deepStrictEqual(alex, {
      userId: ALEX, netBalancePaise: 200000, owesPaise: 0, receivesPaise: 200000, status: 'creditor',
    });
    const blair = groupBalances.members.find((m) => m.userId === BLAIR);
    assert.strictEqual(blair.netBalancePaise, -100000);
    assert.strictEqual(blair.owesPaise, 100000);
    assert.strictEqual(blair.status, 'debtor');

    const alexView = standingsFor(ALEX);
    assert.strictEqual(alexView.myNetPaise, 200000);
    assert.strictEqual(myPositionLabel(alexView.myNetPaise), 'You are owed ₹2,000.00');
    assert.strictEqual(alexView.youAreOwedPaise, 200000);
  });

  await t.test('2. Suggested transfers parse from the real shape', () => {
    const groupBalances = mapGroupBalances(demoBalances);
    assert.deepStrictEqual(groupBalances.suggestedTransfers, [
      { fromUser: BLAIR, toUser: ALEX, amountPaise: 100000 },
      { fromUser: CASEY, toUser: ALEX, amountPaise: 100000 },
    ]);
    const simplified = mapSimplifiedRepayments(demoSimplified);
    assert.strictEqual(simplified.totalTransfers, 2);
    assert.strictEqual(simplified.totalAmountPaise, 200000);
    assert.deepStrictEqual(simplified.suggestedTransfers, groupBalances.suggestedTransfers);
  });

  await t.test('3. Balance status categorization: creditor, debtor and settled', () => {
    const mapped = mapGroupBalances({
      group_id: 'group-multi',
      net_positions: { u1: 50000, u2: -30000, u3: -20000, u4: 0 },
      suggested_transfers: [],
      members: [
        { user_id: 'u1', net_balance_paise: 50000, owes_paise: 0, receives_paise: 50000, status: 'creditor' },
        { user_id: 'u2', net_balance_paise: -30000, owes_paise: 30000, receives_paise: 0, status: 'debtor' },
        { user_id: 'u3', net_balance_paise: -20000, owes_paise: 20000, receives_paise: 0, status: 'debtor' },
        { user_id: 'u4', net_balance_paise: 0, owes_paise: 0, receives_paise: 0, status: 'settled' },
      ],
      total_debt_paise: 50000,
      currency: 'INR',
    });
    assert.deepStrictEqual(mapped.members.map((m) => m.status), ['creditor', 'debtor', 'debtor', 'settled']);
  });

  await t.test('4. Parsing is strict: wrong names, floats or missing fields are rejected', () => {
    const camel = { groupId: 'g', netPositions: {}, suggestedTransfers: [], members: [], totalDebtPaise: 0 };
    assert.throws(() => mapGroupBalances(camel), (e) => e instanceof ApiError && e.code === 'INVALID_RESPONSE');
    assert.throws(() => mapGroupBalances({ ...demoBalances, total_debt_paise: 2000.5 }), ApiError);
    assert.throws(
      () => mapGroupBalances({ ...demoBalances, net_positions: { [ALEX]: '200000' } }),
      ApiError
    );
    assert.throws(
      () => mapGroupBalances({ ...demoBalances, members: [{ ...demoBalances.members[0], status: 'owed' }] }),
      ApiError
    );
    // currency is optional in the schema
    const { currency, ...noCurrency } = demoBalances;
    assert.strictEqual(currency, 'INR');
    assert.strictEqual(mapGroupBalances(noCurrency).currency, 'INR');
  });

  await t.test('5. SettlementResponse parses, including nullable fields', () => {
    const record = mapSettlement(settlementResponse);
    assert.deepStrictEqual(record, {
      id: 'stl-1', groupId: 'group-demo-01', payerId: BLAIR, payeeId: ALEX, amountPaise: 100000,
      status: 'completed', paymentMethod: 'upi', notes: null, settlementDate: '2026-11-19',
      isPartial: false, remainingDebtPaise: 0,
      createdAt: '2026-11-19T10:00:00Z', updatedAt: '2026-11-19T10:00:00Z',
    });
    // GET /settlements omits remaining_debt_paise (null)
    const listed = mapSettlementList([{ ...settlementResponse, remaining_debt_paise: null }]);
    assert.strictEqual(listed[0].remainingDebtPaise, null);
    assert.throws(() => mapSettlementList({}), ApiError);
  });

  await t.test('6. Headline labels for positive, negative and zero positions', () => {
    assert.strictEqual(myPositionLabel(200000), 'You are owed ₹2,000.00');
    assert.strictEqual(myPositionLabel(-100000), 'You owe ₹1,000.00');
    assert.strictEqual(myPositionLabel(0), 'Settled up');
    assert.strictEqual(myPositionLabel(-5), 'You owe ₹0.05');
  });

  await t.test("7. Demo, Alex's view: Blair owes you ₹1,000 and Casey owes you ₹1,000", () => {
    const view = standingsFor(ALEX);
    assert.deepStrictEqual(view.peopleWhoOweYou.map(peerLabel), [
      'Blair owes you ₹1,000.00',
      'Casey owes you ₹1,000.00',
    ]);
    assert.deepStrictEqual(view.peopleYouOwe, []);
    assert.deepStrictEqual(view.settledMembers, []);
  });

  await t.test("8. Demo, Blair's view: You owe ₹1,000 (to Alex)", () => {
    const view = standingsFor(BLAIR);
    assert.strictEqual(myPositionLabel(view.myNetPaise), 'You owe ₹1,000.00');
    assert.deepStrictEqual(view.peopleYouOwe.map(peerLabel), ['You owe Alex ₹1,000.00']);
    assert.strictEqual(view.youOwePaise, 100000);
    assert.deepStrictEqual(view.peopleWhoOweYou, []);
    // Casey still owes Alex, so Casey is NOT shown as settled from Blair's view.
    assert.deepStrictEqual(view.settledMembers, []);
  });

  await t.test('9. After Blair settles ₹1,000: Alex owed ₹1,000, Blair settled up', () => {
    const alex = standingsFor(ALEX, afterBlairSettles);
    assert.strictEqual(myPositionLabel(alex.myNetPaise), 'You are owed ₹1,000.00');
    assert.deepStrictEqual(alex.peopleWhoOweYou.map(peerLabel), ['Casey owes you ₹1,000.00']);
    assert.deepStrictEqual(alex.settledMembers.map(peerLabel), ['Blair is settled up']);

    const blair = standingsFor(BLAIR, afterBlairSettles);
    assert.strictEqual(myPositionLabel(blair.myNetPaise), 'Settled up');
    assert.deepStrictEqual(blair.peopleYouOwe, []);

    const record = mapSettlement(settlementResponse);
    const nameOf = (id) => MEMBERS.find((m) => m.userId === id)?.name ?? 'Group member';
    assert.strictEqual(settlementLabel(record, ALEX, nameOf), 'Blair settled ₹1,000.00 with you');
    assert.strictEqual(settlementLabel(record, BLAIR, nameOf), 'You settled ₹1,000.00 with Alex');
    assert.strictEqual(hasNoBalances(afterBlairSettles.net_positions), false);
    assert.strictEqual(hasNoBalances({ [ALEX]: 0, [BLAIR]: 0 }), true);
  });

  await t.test('10. Partial settlement: amount check and request body', () => {
    assert.deepStrictEqual(checkSettlementAmount('400', 100000), { ok: true, amountPaise: 40000 });
    assert.deepStrictEqual(checkSettlementAmount('1,000.00', 100000), { ok: true, amountPaise: 100000 });
    const over = checkSettlementAmount('1000.01', 100000);
    assert.strictEqual(over.ok, false);
    assert.match(over.message, /cannot be more than ₹1,000\.00/);
    assert.strictEqual(checkSettlementAmount('0', 100000).ok, false);
    assert.strictEqual(checkSettlementAmount('12.345', 100000).ok, false);
    assert.strictEqual(checkSettlementAmount('abc', 100000).ok, false);

    const partial = buildSettlementPayload({
      payerId: BLAIR, payeeId: ALEX, amountPaise: 40000, outstandingPaise: 100000, paymentMethod: 'cash', notes: '  ',
    });
    assert.deepStrictEqual(partial, {
      payerId: BLAIR, payeeId: ALEX, amountPaise: 40000, isFullSettlement: false, paymentMethod: 'cash',
    });
    const full = buildSettlementPayload({
      payerId: BLAIR, payeeId: ALEX, amountPaise: 100000, outstandingPaise: 100000, paymentMethod: 'upi', notes: 'GPay',
    });
    assert.strictEqual(full.isFullSettlement, true);
    assert.strictEqual(full.notes, 'GPay');
    // Only SettlementCreateRequest fields; no reminder flag (removed until T-36).
    assert.deepStrictEqual(Object.keys(full).sort(), ['amountPaise', 'isFullSettlement', 'notes', 'payeeId', 'payerId', 'paymentMethod']);
  });

  await t.test('11. Idempotency key: same on Retry, new for a changed or new submission', async () => {
    const tracker = createSettlementKeyTracker(keyFactory());
    const payload = { payerId: BLAIR, payeeId: ALEX, amountPaise: 100000, isFullSettlement: true, paymentMethod: 'upi' };
    const sent = [];
    let attempt = 0;
    const save = async (_p, key) => {
      sent.push(key);
      attempt += 1;
      if (attempt === 1) throw new ApiError('NETWORK_ERROR', 'Unable to connect to the server.', true);
      return mapSettlement(settlementResponse);
    };
    const first = await runSettlement(payload, tracker, save);
    assert.strictEqual(first.ok, false);
    const retry = await runSettlement(payload, tracker, save);
    assert.strictEqual(retry.ok, true);
    assert.deepStrictEqual(sent, ['key-1', 'key-1']);

    const failing = async () => {
      throw new ApiError('NETWORK_ERROR', 'Unable to connect to the server.', true);
    };
    const changed = await runSettlement({ ...payload, amountPaise: 40000, isFullSettlement: false }, tracker, failing);
    assert.strictEqual(changed.idempotencyKey, 'key-2');

    tracker.reset(); // after a successful save
    const next = await runSettlement(payload, tracker, failing);
    assert.strictEqual(next.idempotencyKey, 'key-3');
  });

  await t.test('12. Values are kept on failure and the server message is shown', async () => {
    const tracker = createSettlementKeyTracker(keyFactory());
    const payload = Object.freeze({ payerId: BLAIR, payeeId: ALEX, amountPaise: 150000, isFullSettlement: false, paymentMethod: 'upi', notes: 'Rent' });
    const snapshot = JSON.stringify(payload);
    const serverError = new ApiError(
      'AMOUNT_EXCEEDS_OUTSTANDING',
      'Settlement amount (150000 paise) exceeds what the payer owes the payee (100000 paise).',
      false
    );
    const outcome = await runSettlement(payload, tracker, async () => {
      throw serverError;
    });
    assert.strictEqual(outcome.ok, false);
    assert.strictEqual(outcome.error, serverError);
    assert.strictEqual(JSON.stringify(payload), snapshot);

    const unexpected = await runSettlement(payload, tracker, async () => {
      throw new TypeError('boom');
    });
    assert.strictEqual(unexpected.error.code, 'SETTLEMENT_FAILED');
    assert.strictEqual(unexpected.error.isRetryable, true);
    assert.strictEqual(unexpected.error.message, SETTLE_FAILED_MESSAGE);
  });

  await t.test('13. Mock client returns the backend shapes and follows the same rules', () => {
    resetMockBalances();
    const g = '/api/v1/groups/demo';
    const balances = mapGroupBalances(mockBalancesGet(`${g}/balances`));
    assert.strictEqual(balances.netPositions[MOCK_ALEX], 200000);
    assert.strictEqual(balances.totalDebtPaise, 200000);
    assert.strictEqual(mapSimplifiedRepayments(mockBalancesGet(`${g}/balances/simplified`)).totalTransfers, 2);
    assert.deepStrictEqual(mapSettlementList(mockBalancesGet(`${g}/settlements`)), []);

    const body = { payer_id: MOCK_BLAIR, payee_id: MOCK_ALEX, is_full_settlement: false, amount_paise: 40000, payment_method: 'upi' };
    const saved = mapSettlement(mockBalancesPost(`${g}/settlements`, body, { 'Idempotency-Key': 'k1' }));
    assert.strictEqual(saved.isPartial, true);
    assert.strictEqual(saved.remainingDebtPaise, 60000);
    // Same key, same body: replay, no second record.
    const replay = mapSettlement(mockBalancesPost(`${g}/settlements`, body, { 'Idempotency-Key': 'k1' }));
    assert.strictEqual(replay.id, saved.id);
    assert.strictEqual(mapSettlementList(mockBalancesGet(`${g}/settlements`)).length, 1);
    assert.throws(
      () => mockBalancesPost(`${g}/settlements`, { ...body, amount_paise: 60001 }, { 'Idempotency-Key': 'k2' }),
      (e) => e.code === 'AMOUNT_EXCEEDS_OUTSTANDING'
    );
    assert.throws(
      () => mockBalancesPost(`${g}/settlements`, { ...body, amount_paise: 1 }, { 'Idempotency-Key': 'k1' }),
      (e) => e.code === 'IDEMPOTENCY_CONFLICT'
    );
    const after = mapGroupBalances(mockBalancesGet(`${g}/balances`));
    assert.strictEqual(after.netPositions[MOCK_BLAIR], -60000);
    assert.strictEqual(after.netPositions[MOCK_ALEX], 160000);
    assert.strictEqual(after.netPositions[MOCK_CASEY], -100000);
    assert.strictEqual(Object.values(after.netPositions).reduce((a, b) => a + b, 0), 0);
    assert.strictEqual(mockBalancesGet('/api/v1/groups/demo'), undefined);
    resetMockBalances();
  });
});
