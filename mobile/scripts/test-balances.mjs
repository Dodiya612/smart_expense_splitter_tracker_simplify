import test from 'node:test';
import assert from 'node:assert';
import {
  mapGroupBalances,
} from '../src/features/balances/services/balancesApi.ts';

test('T-33 / US-10: Group Balances & Settle Up Tests', async (t) => {
  // Demo Dataset:
  // Alex paid ₹3,000 (300,000 paise) for groceries.
  // Split equally among 3 members: Alex, Blair, Casey (₹1,000 / 100,000 paise each).
  // Balances:
  // Alex: +200,000 paise (+₹2,000.00) -> Owed ₹2,000
  // Blair: -100,000 paise (-₹1,000.00) -> Owes ₹1,000
  // Casey: -100,000 paise (-₹1,000.00) -> Owes ₹1,000
  const demoBackendBalances = {
    group_id: 'group-demo-01',
    currency: 'INR',
    net_positions: {
      'user-alex': 200000,
      'user-blair': -100000,
      'user-casey': -100000,
    },
    suggested_transfers: [
      { from_user: 'user-blair', to_user: 'user-alex', amount_paise: 100000 },
      { from_user: 'user-casey', to_user: 'user-alex', amount_paise: 100000 },
    ],
    total_debt_paise: 200000,
  };

  await t.test('1. Definition of Done: Alex is correctly shown as owed ₹2,000 (200,000 paise)', () => {
    const groupBalances = mapGroupBalances(demoBackendBalances, 'group-demo-01');
    assert.strictEqual(groupBalances.groupId, 'group-demo-01');
    assert.strictEqual(groupBalances.currency, 'INR');
    assert.strictEqual(groupBalances.members.length, 3);
    assert.strictEqual(groupBalances.totalDebtPaise, 200000);

    const alexMember = groupBalances.members.find((m) => m.userId === 'user-alex');
    assert.ok(alexMember, 'Alex should exist in members list');
    assert.strictEqual(alexMember.netBalancePaise, 200000);
    assert.strictEqual(alexMember.receivesPaise, 200000);
    assert.strictEqual(alexMember.owesPaise, 0);
    assert.strictEqual(alexMember.status, 'creditor');

    const blairMember = groupBalances.members.find((m) => m.userId === 'user-blair');
    assert.ok(blairMember);
    assert.strictEqual(blairMember.netBalancePaise, -100000);
    assert.strictEqual(blairMember.owesPaise, 100000);
    assert.strictEqual(blairMember.receivesPaise, 0);
    assert.strictEqual(blairMember.status, 'debtor');

    const caseyMember = groupBalances.members.find((m) => m.userId === 'user-casey');
    assert.ok(caseyMember);
    assert.strictEqual(caseyMember.netBalancePaise, -100000);
    assert.strictEqual(caseyMember.owesPaise, 100000);
    assert.strictEqual(caseyMember.receivesPaise, 0);
    assert.strictEqual(caseyMember.status, 'debtor');
  });

  await t.test('2. Suggested Transfers Verification for Alex, Blair, and Casey', () => {
    const groupBalances = mapGroupBalances(demoBackendBalances, 'group-demo-01');
    assert.strictEqual(groupBalances.suggestedTransfers.length, 2);

    const t1 = groupBalances.suggestedTransfers[0];
    assert.strictEqual(t1.fromUser, 'user-blair');
    assert.strictEqual(t1.toUser, 'user-alex');
    assert.strictEqual(t1.amountPaise, 100000);

    const t2 = groupBalances.suggestedTransfers[1];
    assert.strictEqual(t2.fromUser, 'user-casey');
    assert.strictEqual(t2.toUser, 'user-alex');
    assert.strictEqual(t2.amountPaise, 100000);
  });

  await t.test('3. Balance Status Categorization: creditor, debtor, and settled', () => {
    const rawData = {
      group_id: 'group-multi',
      currency: 'INR',
      net_positions: {
        'u1': 50000,
        'u2': -30000,
        'u3': 0,
      },
      suggested_transfers: [],
    };

    const mapped = mapGroupBalances(rawData, 'group-multi');
    const u1 = mapped.members.find((m) => m.userId === 'u1');
    const u2 = mapped.members.find((m) => m.userId === 'u2');
    const u3 = mapped.members.find((m) => m.userId === 'u3');

    assert.strictEqual(u1?.status, 'creditor');
    assert.strictEqual(u2?.status, 'debtor');
    assert.strictEqual(u3?.status, 'settled');
  });
});
