import test from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { estimatePasswordStrength } from '../src/features/auth/utils/passwordStrength.ts';
import {
  EMPTY_CHANGE_PASSWORD_VALUES,
  canSubmitChangePassword,
  mapChangePasswordError,
  passwordRequirements,
  successMessage,
  validateChangePassword,
} from '../src/features/auth/utils/changePassword.ts';
import { ApiError } from '../src/services/api/types.ts';
import { FastApiClient } from '../src/services/api/fastApiClient.ts';
import { _resetRefreshMutex } from '../src/services/api/authInterceptor.ts';
import { tokenStorage } from '../src/services/auth/tokenStorage.ts';
import {
  mockAddPasswordChangedNotice,
  mockNotificationsGet,
  mockNotificationsPut,
} from '../src/services/mock/mockNotifications.ts';
import { NOTIFICATION_KINDS } from '../src/features/notifications/types.ts';
import { notificationTarget, preferenceLabel } from '../src/features/notifications/utils/parseNotifications.ts';

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURE = resolve(here, '../../backend/tests/fixtures/password_strength_cases.json');
const USER = ['Priya Patel', 'priya.patel@example.in'];
const STRONG = 'Monsoon-Chai-4-Two!';
const form = (overrides = {}) => ({
  currentPassword: 'Password123!',
  newPassword: STRONG,
  confirmNewPassword: STRONG,
  ...overrides,
});

// ---------------------------------------------------------------------------
// Strength: identical to the backend rules
// ---------------------------------------------------------------------------

test('T-50: strength matches the backend on every shared fixture case', () => {
  const { cases } = JSON.parse(readFileSync(FIXTURE, 'utf8'));
  assert.ok(cases.length >= 20);
  for (const c of cases) {
    const r = estimatePasswordStrength(c.password, c.user_inputs);
    assert.deepStrictEqual(
      { score: r.score, effectiveLength: r.effectiveLength, isCommon: r.isCommon },
      { score: c.score, effectiveLength: c.effective_length, isCommon: c.is_common },
      `case ${JSON.stringify(c.password)}`
    );
  }
});

test('T-50: strength gives a label and hints, and updates as the password grows', () => {
  const weak = estimatePasswordStrength('aaaaaaaaaaaa');
  assert.strictEqual(weak.score, 0);
  assert.strictEqual(weak.label, 'Very weak');
  assert.ok(weak.feedback.length > 0);
  const scores = ['Mon', 'Monsoon', 'Monsoon-Ch', STRONG].map((p) => estimatePasswordStrength(p).score);
  for (let i = 1; i < scores.length; i++) assert.ok(scores[i] >= scores[i - 1], scores.join(','));
  assert.ok(scores[scores.length - 1] >= 3);
});

// ---------------------------------------------------------------------------
// Form validation
// ---------------------------------------------------------------------------

test('T-50: empty fields are each reported and block submission', () => {
  const errors = validateChangePassword(EMPTY_CHANGE_PASSWORD_VALUES, USER);
  assert.ok(errors.currentPassword && errors.newPassword && errors.confirmNewPassword);
  assert.strictEqual(canSubmitChangePassword(EMPTY_CHANGE_PASSWORD_VALUES, USER), false);
});

test('T-50: a new password shorter than 10 characters is rejected', () => {
  const values = form({ newPassword: 'Zq9!kL2#x', confirmNewPassword: 'Zq9!kL2#x' });
  assert.match(validateChangePassword(values, USER).newPassword, /at least 10 characters/);
  assert.strictEqual(canSubmitChangePassword(values, USER), false);
  assert.strictEqual(passwordRequirements(values, USER).find((r) => r.key === 'length').met, false);
});

test('T-50: a new password scoring below 3/4 is rejected with a hint', () => {
  for (const weak of ['Password123456', 'aaaaaaaaaaaa', 'PriyaPatel2024']) {
    const values = form({ newPassword: weak, confirmNewPassword: weak });
    assert.match(validateChangePassword(values, USER).newPassword, /Too weak \(\d\/4\)/, weak);
    assert.strictEqual(canSubmitChangePassword(values, USER), false, weak);
  }
});

test('T-50: matching confirmation passes; a mismatch is reported', () => {
  assert.deepStrictEqual(validateChangePassword(form(), USER), {});
  assert.strictEqual(canSubmitChangePassword(form(), USER), true);
  assert.ok(passwordRequirements(form(), USER).every((r) => r.met));

  const mismatch = form({ confirmNewPassword: `${STRONG}x` });
  assert.strictEqual(validateChangePassword(mismatch, USER).confirmNewPassword, 'Passwords do not match.');
  assert.strictEqual(canSubmitChangePassword(mismatch, USER), false);
  assert.strictEqual(passwordRequirements(mismatch, USER).find((r) => r.key === 'match').met, false);
});

test('T-50: reusing the current password is rejected', () => {
  const values = form({ currentPassword: STRONG });
  assert.match(validateChangePassword(values, USER).newPassword, /different/);
});

// ---------------------------------------------------------------------------
// Server error mapping and success copy
// ---------------------------------------------------------------------------

test('T-50: server errors map to the right field or a banner', () => {
  assert.deepStrictEqual(
    mapChangePasswordError(new ApiError('INVALID_CURRENT_PASSWORD', 'x')).fieldErrors,
    { currentPassword: 'Your current password is incorrect.' }
  );
  const weak = mapChangePasswordError(
    new ApiError('WEAK_PASSWORD', 'Too weak (2/4).', false, [{ msg: 'Add more characters.' }])
  );
  assert.strictEqual(weak.fieldErrors.newPassword, 'Too weak (2/4). Add more characters.');
  assert.ok(mapChangePasswordError(new ApiError('PASSWORD_MISMATCH', 'x')).fieldErrors.confirmNewPassword);
  const limited = mapChangePasswordError(new ApiError('RATE_LIMIT_EXCEEDED', 'Try again in 60 seconds.'));
  assert.deepStrictEqual(limited, { fieldErrors: {}, banner: 'Try again in 60 seconds.' });
});

test('T-50: the in-app confirmation says what happened to other devices', () => {
  assert.match(successMessage(0), /still signed in/);
  assert.match(successMessage(1), /signed out on 1 other device;/);
  assert.match(successMessage(3), /3 other devices/);
});

// ---------------------------------------------------------------------------
// FastApiClient.changePassword with a stubbed fetch
// ---------------------------------------------------------------------------

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, statusText: '', json: async () => body });
const OLD = { accessToken: 'old-access', refreshToken: 'old-refresh' };
const NEW = { accessToken: 'new-access', refreshToken: 'new-refresh', tokenType: 'bearer', expiresIn: 900 };
const SUCCESS = { message: 'Your password has been changed.', tokens: NEW, revokedSessions: 2 };

async function withFetch(handler, run) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    const call = {
      url: String(url),
      auth: options.headers?.Authorization,
      body: options.body ? JSON.parse(options.body) : undefined,
    };
    calls.push(call);
    return handler(call, calls);
  };
  _resetRefreshMutex();
  await tokenStorage.clearAll();
  await tokenStorage.saveTokens(OLD);
  try {
    await run(calls);
  } finally {
    globalThis.fetch = original;
    _resetRefreshMutex();
    await tokenStorage.clearAll();
  }
}

test('T-50: a successful change stores the new tokens for this device', async () => {
  await withFetch(
    (call) => (call.url.endsWith('/auth/change-password') ? json(200, SUCCESS) : json(500, {})),
    async (calls) => {
      const res = await new FastApiClient('http://api').changePassword(form());
      assert.strictEqual(res.revokedSessions, 2);
      assert.strictEqual(await tokenStorage.getAccessToken(), 'new-access');
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'new-refresh');
      assert.strictEqual(calls.length, 1);
      assert.strictEqual(calls[0].auth, 'Bearer old-access');
      assert.deepStrictEqual(calls[0].body, {
        currentPassword: 'Password123!',
        newPassword: STRONG,
        confirmNewPassword: STRONG,
      });
    }
  );
});

test('T-50: a wrong current password keeps the session and does not refresh', async () => {
  await withFetch(
    () => json(400, { code: 'INVALID_CURRENT_PASSWORD', message: 'Your current password is incorrect.' }),
    async (calls) => {
      await assert.rejects(
        new FastApiClient('http://api').changePassword(form({ currentPassword: 'nope' })),
        (err) => err instanceof ApiError && err.code === 'INVALID_CURRENT_PASSWORD'
      );
      assert.strictEqual(calls.length, 1);
      assert.strictEqual(await tokenStorage.getAccessToken(), 'old-access');
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'old-refresh');
    }
  );
});

test('T-50: an access token without a session id is refreshed once, then the change is retried', async () => {
  await withFetch(
    (call, calls) => {
      if (call.url.endsWith('/auth/refresh')) {
        return json(200, { accessToken: 'refreshed-access', refreshToken: 'refreshed-refresh' });
      }
      if (calls.filter((c) => c.url.endsWith('/auth/change-password')).length === 1) {
        return json(401, { code: 'SESSION_NOT_IDENTIFIED', message: 'Refresh needed.' });
      }
      return json(200, SUCCESS);
    },
    async (calls) => {
      await new FastApiClient('http://api').changePassword(form());
      assert.deepStrictEqual(calls.map((c) => c.url.split('/').pop()), ['change-password', 'refresh', 'change-password']);
      assert.strictEqual(calls[1].body.refreshToken, 'old-refresh');
      assert.strictEqual(calls[2].auth, 'Bearer refreshed-access');
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'new-refresh');
    }
  );
});

test('T-50: a request that hits 401 during the change waits and reuses the new token (no stale refresh)', async () => {
  let releaseChange;
  const changeGate = new Promise((r) => (releaseChange = r));
  await withFetch(
    async (call) => {
      if (call.url.endsWith('/auth/change-password')) {
        await changeGate;
        return json(200, SUCCESS);
      }
      if (call.url.endsWith('/auth/refresh')) return json(200, { accessToken: 'x', refreshToken: 'y' });
      // A protected call: the old token is stale once the password changes.
      return call.auth === 'Bearer new-access' ? json(200, { ok: true }) : json(401, { code: 'TOKEN_REVOKED' });
    },
    async (calls) => {
      const client = new FastApiClient('http://api');
      const change = client.changePassword(form());
      await new Promise((r) => setTimeout(r, 5));
      const other = client.get('/api/v1/notifications/unread-count');
      await new Promise((r) => setTimeout(r, 5));
      releaseChange();
      await change;
      assert.deepStrictEqual(await other, { ok: true });
      // The replaced refresh token was never sent: sending it would look like token reuse
      // to the server and sign this device out.
      assert.strictEqual(calls.some((c) => c.url.endsWith('/auth/refresh')), false);
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'new-refresh');
    }
  );
});

// ---------------------------------------------------------------------------
// Notification centre (T-36) integration
// ---------------------------------------------------------------------------

test('T-50: password_changed is a known kind with a label, icon-safe target and no group link', () => {
  assert.ok(NOTIFICATION_KINDS.includes('password_changed'));
  assert.strictEqual(preferenceLabel('password_changed').label, 'Password changes');
  assert.strictEqual(
    notificationTarget({ id: 'n', kind: 'password_changed', title: '', body: '', groupId: null, groupName: null, isRead: false, createdAt: '' }),
    null
  );
});

test('T-50: a successful mock change adds one unread security notice; it cannot be switched off', () => {
  const before = mockNotificationsGet('/api/v1/notifications/unread-count').unread_count;
  mockAddPasswordChangedNotice(1);
  const page = mockNotificationsGet('/api/v1/notifications');
  assert.strictEqual(page.items[0].kind, 'password_changed');
  assert.strictEqual(page.items[0].group_id, null);
  assert.match(page.items[0].body, /signed out on 1 other device\./);
  assert.strictEqual(mockNotificationsGet('/api/v1/notifications/unread-count').unread_count, before + 1);

  const pref = mockNotificationsGet('/api/v1/notification-preferences').preferences.find(
    (p) => p.kind === 'password_changed'
  );
  assert.deepStrictEqual(pref, { kind: 'password_changed', enabled: true, can_disable: false });
  assert.throws(() =>
    mockNotificationsPut('/api/v1/notification-preferences', {
      preferences: [{ kind: 'password_changed', enabled: false }],
    })
  );
});
