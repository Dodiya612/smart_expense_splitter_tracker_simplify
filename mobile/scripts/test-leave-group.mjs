import test from 'node:test';
import assert from 'node:assert';
import { leaveCheckFor, leaveDialogText, leaveErrorMessage } from '../src/features/groups/utils/leaveGroup.ts';

test('T-35 / US-22: balance decides warning or plain confirm', () => {
  assert.deepStrictEqual(leaveCheckFor(0), { kind: 'settled' });
  assert.deepStrictEqual(leaveCheckFor(-100000), { kind: 'you_owe', amountPaise: 100000 });
  assert.deepStrictEqual(leaveCheckFor(200000), { kind: 'owed_to_you', amountPaise: 200000 });
  // Even one paisa counts as unsettled.
  assert.strictEqual(leaveCheckFor(-1).kind, 'you_owe');
  assert.strictEqual(leaveCheckFor(1).kind, 'owed_to_you');
});

test('T-35 Done when: a member with a balance sees the warning first', () => {
  const owes = leaveDialogText(leaveCheckFor(-100000), 'Flat Expenses');
  assert.strictEqual(owes.title, 'You still owe money');
  assert.match(owes.message, /You owe ₹1,000\.00 in "Flat Expenses"/);
  assert.match(owes.message, /Settle up before you leave/);
  assert.match(owes.message, /history/);

  const owed = leaveDialogText(leaveCheckFor(200000), 'Flat Expenses');
  assert.strictEqual(owed.title, 'You are still owed money');
  assert.match(owed.message, /Others owe you ₹2,000\.00/);
});

test('T-35: a settled member gets a plain confirmation that mentions history', () => {
  const text = leaveDialogText(leaveCheckFor(0), 'Goa Trip');
  assert.strictEqual(text.title, 'Leave "Goa Trip"?');
  assert.match(text.message, /Past expenses stay in the group history/);
  assert.match(text.message, /rejoin/);
});

test('T-35: backend errors read plainly', () => {
  assert.match(leaveErrorMessage('CANNOT_REMOVE_OWNER', 'x'), /owner can't leave/);
  assert.match(leaveErrorMessage('GROUP_ACCESS_DENIED', 'x'), /no longer a member/);
  assert.strictEqual(leaveErrorMessage('NETWORK_ERROR', 'No connection'), 'No connection');
});
