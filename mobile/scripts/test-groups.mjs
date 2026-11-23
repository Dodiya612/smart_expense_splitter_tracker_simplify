import test from 'node:test';
import assert from 'node:assert';
import {
  buildInviteMessage,
  extractJoinCode,
  joinErrorMessage,
  joinPath,
  normalizeJoinCode,
  validateJoinCode,
} from '../src/features/groups/utils/joinCode.ts';
import { toCreateGroupInput, validateCreateGroup } from '../src/features/groups/utils/validation.ts';
import { groupTypeInfo, initials, isAdminRole, memberCountLabel } from '../src/features/groups/utils/groupDisplay.ts';
import { consumePendingJoinPath, setPendingJoinCode } from '../src/features/groups/utils/pendingJoin.ts';
import { forgetJoinCode, getRememberedJoinCode, rememberJoinCode } from '../src/features/groups/utils/joinCodeCache.ts';

import { mapGroupDetail, mapGroupSummary, mapJoinCode } from '../src/features/groups/services/groupsApi.ts';

test('T-29 / US-17: join codes', async (t) => {
  await t.test('normalizes case, spaces and dashes', () => {
    assert.strictEqual(normalizeJoinCode(' 7k3m-q9xa '), '7K3MQ9XA');
    assert.strictEqual(normalizeJoinCode('7K3M Q9XA'), '7K3MQ9XA');
  });

  await t.test('extracts the code from every invite link form', () => {
    assert.strictEqual(extractJoinCode('7k3mq9xa'), '7K3MQ9XA');
    assert.strictEqual(extractJoinCode('mobile://join/7K3MQ9XA'), '7K3MQ9XA');
    assert.strictEqual(extractJoinCode('exp://192.168.1.5:8081/--/join/7k3mq9xa'), '7K3MQ9XA');
    assert.strictEqual(extractJoinCode('https://example.test/join/7K3MQ9XA/'), '7K3MQ9XA');
    assert.strictEqual(extractJoinCode('https://example.test/join/7K3MQ9XA?ref=x'), '7K3MQ9XA');
  });

  await t.test('validates codes the backend would accept', () => {
    assert.strictEqual(validateJoinCode('7K3MQ9XA'), undefined);
    assert.strictEqual(validateJoinCode(''), 'Enter the invite code.');
    assert.strictEqual(validateJoinCode('ABC'), 'Invite codes are 8 characters long.');
    assert.strictEqual(validateJoinCode('A'.repeat(33)), 'Invite codes are 8 characters long.');
    assert.strictEqual(validateJoinCode('7K3MQ9X!'), 'Use only letters and numbers.');
  });

  await t.test('builds the /join/<code> route and invite text', () => {
    assert.strictEqual(joinPath('7k3m-q9xa'), '/join/7K3MQ9XA');
    const msg = buildInviteMessage('Flat 302', '7K3MQ9XA', 'mobile://join/7K3MQ9XA');
    assert.ok(msg.includes('Flat 302'));
    assert.ok(msg.includes('Invite code: 7K3MQ9XA'));
    assert.ok(msg.includes('mobile://join/7K3MQ9XA'));
    assert.ok(msg.includes('7 days'));
  });

  await t.test('maps backend join errors to plain messages', () => {
    assert.match(joinErrorMessage('JOIN_CODE_EXPIRED', 'x'), /expired/);
    assert.match(joinErrorMessage('JOIN_CODE_REVOKED', 'x'), /turned off/);
    assert.match(joinErrorMessage('INVALID_JOIN_CODE', 'x'), /not valid/);
    assert.match(joinErrorMessage('ALREADY_MEMBER', 'x'), /already a member/);
    assert.strictEqual(joinErrorMessage('NETWORK_ERROR', 'No connection'), 'No connection');
  });
});

test('T-29 / US-17: create group validation', async (t) => {
  await t.test('requires a name and a type', () => {
    const errors = validateCreateGroup({ name: '   ', description: '', type: null });
    assert.ok(errors.name);
    assert.ok(errors.type);
    assert.strictEqual(errors.description, undefined);
  });

  await t.test('enforces backend length limits', () => {
    const errors = validateCreateGroup({ name: 'a'.repeat(101), description: 'b'.repeat(501), type: 'flat' });
    assert.ok(errors.name);
    assert.ok(errors.description);
    assert.deepStrictEqual(
      validateCreateGroup({ name: 'a'.repeat(100), description: 'b'.repeat(500), type: 'flat' }),
      {}
    );
  });

  await t.test('rejects unknown group types', () => {
    assert.ok(validateCreateGroup({ name: 'Goa', description: '', type: 'office' }).type);
  });

  await t.test('trims the payload and drops an empty description', () => {
    assert.deepStrictEqual(toCreateGroupInput({ name: '  Goa trip ', description: '   ', type: 'trip' }), {
      name: 'Goa trip',
      description: undefined,
      type: 'trip',
    });
  });
});

test('T-29 / US-17: display helpers', () => {
  assert.strictEqual(groupTypeInfo('flat').label, 'Flat');
  assert.strictEqual(groupTypeInfo('unknown').label, 'Friends');
  assert.strictEqual(memberCountLabel(1), '1 member');
  assert.strictEqual(memberCountLabel(4), '4 members');
  assert.strictEqual(initials('Harshul Patel'), 'HP');
  assert.strictEqual(initials('vivek'), 'V');
  assert.strictEqual(initials('  '), '?');
  assert.ok(isAdminRole('admin'));
  assert.ok(!isAdminRole('member'));
  assert.ok(!isAdminRole(undefined));
});

test('T-29 / US-17: invite link opened while logged out', () => {
  assert.strictEqual(consumePendingJoinPath(), null);
  setPendingJoinCode('7k3m-q9xa');
  assert.strictEqual(consumePendingJoinPath(), '/join/7K3MQ9XA');
  assert.strictEqual(consumePendingJoinPath(), null, 'a pending join is used only once');
  setPendingJoinCode('   ');
  assert.strictEqual(consumePendingJoinPath(), null);
});

test('T-29 / US-17: one-time join code cache', () => {
  assert.strictEqual(getRememberedJoinCode('g1'), null);
  rememberJoinCode({ groupId: 'g1', code: '7K3MQ9XA', expiresAt: '' });
  assert.strictEqual(getRememberedJoinCode('g1')?.code, '7K3MQ9XA');
  rememberJoinCode({ groupId: 'g1', code: '', expiresAt: '' });
  assert.strictEqual(getRememberedJoinCode('g1')?.code, '7K3MQ9XA', 'empty codes are ignored');
  forgetJoinCode('g1');
  assert.strictEqual(getRememberedJoinCode('g1'), null);
});

test('T-29 / US-17: API mappers read the camelCase wire format', () => {
  // Shapes copied from backend/app/schemas/group.py (BaseSchema serializes to camelCase).
  const created = mapGroupDetail({
    id: 'g1',
    name: 'Flat 302',
    description: null,
    type: 'flat',
    createdBy: 'u1',
    archivedAt: null,
    createdAt: '2026-11-18T10:00:00Z',
    updatedAt: '2026-11-18T10:00:00Z',
    members: [
      { userId: 'u1', name: 'Harshul', email: 'h@example.test', role: 'admin', status: 'active', joinedAt: '2026-11-18T10:00:00Z' },
    ],
    currentUserRole: 'admin',
    joinCode: '7K3MQ9XA',
  });
  assert.strictEqual(created.description, undefined);
  assert.strictEqual(created.joinCode, '7K3MQ9XA');
  assert.strictEqual(created.members.length, 1);
  assert.strictEqual(created.members[0].userId, 'u1');
  assert.strictEqual(created.members[0].role, 'admin');
  assert.strictEqual(created.currentUserRole, 'admin');

  const summary = mapGroupSummary({
    id: 'g1', name: 'Flat 302', type: 'flat', createdBy: 'u1', createdAt: 'x', memberCount: 3, currentUserRole: 'member',
  });
  assert.strictEqual(summary.memberCount, 3);
  assert.strictEqual(summary.currentUserRole, 'member');

  const snake = mapGroupSummary({ id: 'g2', name: 'Goa', type: 'trip', created_by: 'u2', created_at: 'y', member_count: 2, current_user_role: 'admin' });
  assert.strictEqual(snake.memberCount, 2);
  assert.strictEqual(snake.createdBy, 'u2');

  const code = mapJoinCode({ groupId: 'g1', code: 'ABCDEFGH', expiresAt: '2026-11-25T10:00:00Z' });
  assert.deepStrictEqual(code, { groupId: 'g1', code: 'ABCDEFGH', expiresAt: '2026-11-25T10:00:00Z' });
});
