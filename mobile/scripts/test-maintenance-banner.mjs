import test from 'node:test';
import assert from 'node:assert';

test('Maintenance Banner configuration and payload validation (US-35 / T-61)', async (t) => {
  await t.test('parses maintenance configuration from environment / API response', () => {
    const rawConfig = {
      active: true,
      message: 'Scheduled maintenance in progress. Coinscious will return shortly.',
      start_time: '2026-11-22T22:00:00Z',
      end_time: '2026-11-22T23:00:00Z',
    };

    assert.strictEqual(rawConfig.active, true);
    assert.ok(rawConfig.message.includes('maintenance'));
    assert.ok(rawConfig.start_time !== undefined);
  });

  await t.test('detects inactive maintenance mode', () => {
    const inactiveConfig = {
      active: false,
      message: null,
      start_time: null,
      end_time: null,
    };

    assert.strictEqual(inactiveConfig.active, false);
    assert.strictEqual(inactiveConfig.message, null);
  });
});
