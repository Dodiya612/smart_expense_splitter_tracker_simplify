import test from 'node:test';
import assert from 'node:assert';
import {
  createSubmissionKeyTracker,
  runSubmission,
  SAVE_FAILED_MESSAGE,
  submissionSignature,
} from '../src/features/expenses/utils/submission.ts';
import { ApiError } from '../src/services/api/types.ts';

// US-34 / T-38: a failed save keeps the form, Retry reuses the same
// Idempotency-Key, and only a new submission gets a new key.

function keyFactory() {
  let n = 0;
  return () => `key-${++n}`;
}

const FORM = Object.freeze({
  amountRaw: '250.00',
  categoryId: 'food',
  date: '2026-11-19',
  paymentMode: 'upi',
  notes: 'Lunch with team',
  isRecurring: false,
});

function droppedConnection() {
  return new ApiError(
    'NETWORK_ERROR',
    'Unable to connect to the server. Please check your internet connection and try again.',
    true
  );
}

test('T-38 / US-34: expense form save errors and idempotent retries', async (t) => {
  await t.test('retry of the same submission reuses the same key', async () => {
    const tracker = createSubmissionKeyTracker(keyFactory());
    const sentKeys = [];
    let attempt = 0;
    const save = async (_values, key) => {
      sentKeys.push(key);
      attempt += 1;
      if (attempt === 1) throw droppedConnection();
      return { id: 'saved-1' };
    };

    const first = await runSubmission(FORM, tracker, save);
    assert.strictEqual(first.ok, false);
    const retry = await runSubmission(FORM, tracker, save);
    assert.strictEqual(retry.ok, true);
    assert.deepStrictEqual(sentKeys, ['key-1', 'key-1']);
  });

  await t.test('changing a value after a failure is a new submission with a new key', async () => {
    const tracker = createSubmissionKeyTracker(keyFactory());
    const failing = async () => {
      throw droppedConnection();
    };
    const first = await runSubmission(FORM, tracker, failing);
    const edited = { ...FORM, amountRaw: '275.00' };
    const second = await runSubmission(edited, tracker, failing);
    assert.strictEqual(first.idempotencyKey, 'key-1');
    assert.strictEqual(second.idempotencyKey, 'key-2');
    // Going back to the first values is again a different submission.
    const third = await runSubmission(FORM, tracker, failing);
    assert.strictEqual(third.idempotencyKey, 'key-3');
  });

  await t.test('whitespace-only changes are still the same submission', async () => {
    const tracker = createSubmissionKeyTracker(keyFactory());
    const failing = async () => {
      throw droppedConnection();
    };
    const a = await runSubmission(FORM, tracker, failing);
    const b = await runSubmission({ ...FORM, notes: '  Lunch with team  ' }, tracker, failing);
    assert.strictEqual(a.idempotencyKey, b.idempotencyKey);
    assert.strictEqual(
      submissionSignature(FORM),
      submissionSignature({ ...FORM, amountRaw: ' 250.00 ' })
    );
  });

  await t.test('after a successful save the next submission gets a new key', async () => {
    const tracker = createSubmissionKeyTracker(keyFactory());
    const ok = async () => ({ id: 'x' });
    const first = await runSubmission(FORM, tracker, ok);
    tracker.reset(); // what useExpenseForm does after a successful add
    const second = await runSubmission(FORM, tracker, ok);
    assert.strictEqual(first.idempotencyKey, 'key-1');
    assert.strictEqual(second.idempotencyKey, 'key-2');
  });

  await t.test('a failed save keeps every value and returns a retryable error', async () => {
    const tracker = createSubmissionKeyTracker(keyFactory());
    const values = { ...FORM };
    const snapshot = JSON.stringify(values);
    const outcome = await runSubmission(values, tracker, async () => {
      throw droppedConnection();
    });
    assert.strictEqual(outcome.ok, false);
    assert.strictEqual(JSON.stringify(values), snapshot);
    assert.strictEqual(outcome.error.code, 'NETWORK_ERROR');
    assert.strictEqual(outcome.error.isRetryable, true);
    assert.ok(outcome.error.message.length > 0);
  });

  await t.test('a server error envelope is passed through unchanged', async () => {
    const tracker = createSubmissionKeyTracker(keyFactory());
    const serverError = new ApiError(
      'INTERNAL_SERVER_ERROR',
      'An unexpected server error occurred. Please try again later.',
      true
    );
    const outcome = await runSubmission(FORM, tracker, async () => {
      throw serverError;
    });
    assert.strictEqual(outcome.ok, false);
    assert.strictEqual(outcome.error, serverError);
  });

  await t.test('an unexpected error becomes a retryable "form kept" error', async () => {
    const tracker = createSubmissionKeyTracker(keyFactory());
    const outcome = await runSubmission(FORM, tracker, async () => {
      throw new TypeError('boom');
    });
    assert.strictEqual(outcome.ok, false);
    assert.ok(outcome.error instanceof ApiError);
    assert.strictEqual(outcome.error.code, 'UNKNOWN_ERROR');
    assert.strictEqual(outcome.error.isRetryable, true);
    assert.strictEqual(outcome.error.message, SAVE_FAILED_MESSAGE);
  });

  await t.test('a version conflict is not retryable and keeps its code', async () => {
    const tracker = createSubmissionKeyTracker(keyFactory());
    const outcome = await runSubmission(FORM, tracker, async () => {
      throw new ApiError('VERSION_CONFLICT', 'This expense changed', false);
    });
    assert.strictEqual(outcome.ok, false);
    assert.strictEqual(outcome.error.code, 'VERSION_CONFLICT');
    assert.strictEqual(outcome.error.isRetryable, false);
  });
});
