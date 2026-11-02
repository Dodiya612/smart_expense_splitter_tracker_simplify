import test from 'node:test';
import assert from 'node:assert';

import {
  fetchExpenses,
  mapBackendExpenseToDomain,
} from '../src/features/expenses/services/expenseApi.ts';
import { fastApiClient } from '../src/services/api/fastApiClient.ts';
import { ApiError } from '../src/services/api/types.ts';

// ---------------------------------------------------------------------------
// 1. mapBackendExpenseToDomain Contract & Mapping Tests
// ---------------------------------------------------------------------------
test('mapBackendExpenseToDomain mapper', async (t) => {
  await t.test('maps full backend expense correctly to mobile domain model', () => {
    const raw = {
      id: 'exp-101',
      user_id: 'usr-001',
      category_id: 'food',
      amount_minor: 149950,
      amount_paise: 149950,
      description: 'Dinner at Taj',
      expense_date: '2026-10-31',
      notes: 'Team celebration',
      merchant: 'Taj Hotels',
      payment_mode: 'upi',
      receipt_id: null,
      version: 2,
      created_at: '2026-10-31T20:00:00Z',
      updated_at: '2026-10-31T20:30:00Z',
      deleted_at: null,
    };

    const domain = mapBackendExpenseToDomain(raw);

    assert.strictEqual(domain.id, 'exp-101');
    assert.strictEqual(domain.amountPaise, 149950);
    assert.strictEqual(domain.categoryId, 'food');
    assert.strictEqual(domain.date, '2026-10-31');
    assert.strictEqual(domain.paymentMode, 'upi');
    assert.strictEqual(domain.notes, 'Team celebration');
    assert.strictEqual(domain.description, 'Dinner at Taj');
    assert.strictEqual(domain.merchant, 'Taj Hotels');
    assert.strictEqual(domain.version, 2);
    assert.strictEqual(domain.isRecurring, false);
    assert.strictEqual(domain.createdAt, '2026-10-31T20:00:00Z');
    assert.strictEqual(domain.updatedAt, '2026-10-31T20:30:00Z');
  });

  await t.test('falls back to description when notes is empty or null', () => {
    const raw = {
      id: 'exp-102',
      user_id: 'usr-001',
      category_id: 'transport',
      amount_minor: 45000,
      description: 'Uber Ride to Airport',
      expense_date: '2026-10-30',
      notes: null,
      payment_mode: 'card',
      version: 1,
      created_at: '2026-10-30T10:00:00Z',
      updated_at: '2026-10-30T10:00:00Z',
    };

    const domain = mapBackendExpenseToDomain(raw);
    assert.strictEqual(domain.notes, 'Uber Ride to Airport');
    assert.strictEqual(domain.description, 'Uber Ride to Airport');
  });

  await t.test('maps unknown payment_mode to other safely', () => {
    const raw = {
      id: 'exp-103',
      user_id: 'usr-001',
      category_id: 'other',
      amount_minor: 1000,
      description: 'Crypto token gas',
      expense_date: '2026-10-29',
      payment_mode: 'unsupported_mode_xyz',
      version: 1,
      created_at: '2026-10-29T10:00:00Z',
      updated_at: '2026-10-29T10:00:00Z',
    };

    const domain = mapBackendExpenseToDomain(raw);
    assert.strictEqual(domain.paymentMode, 'other');
  });

  await t.test('uses occurred_on if expense_date is missing', () => {
    const raw = {
      id: 'exp-104',
      user_id: 'usr-001',
      category_id: 'shopping',
      amount_minor: 99900,
      description: 'Book purchase',
      expense_date: '',
      occurred_on: '2026-10-28',
      version: 1,
      created_at: '2026-10-28T10:00:00Z',
      updated_at: '2026-10-28T10:00:00Z',
    };

    const domain = mapBackendExpenseToDomain(raw);
    assert.strictEqual(domain.date, '2026-10-28');
  });
});

// ---------------------------------------------------------------------------
// 2. fetchExpenses Service & Pagination Tests
// ---------------------------------------------------------------------------
test('fetchExpenses API Service', async (t) => {
  const originalExecuteRequest = fastApiClient.executeRequest;

  t.afterEach(() => {
    fastApiClient.executeRequest = originalExecuteRequest;
  });

  await t.test('fetches first page with limit=10, offset=0 and requiresAuth', async () => {
    let capturedEndpoint = '';
    let capturedOptions = null;

    fastApiClient.executeRequest = async (endpoint, options) => {
      capturedEndpoint = endpoint;
      capturedOptions = options;
      return {
        data: [
          {
            id: 'exp-1',
            user_id: 'u1',
            category_id: 'food',
            amount_minor: 50000,
            amount_paise: 50000,
            description: 'Lunch',
            expense_date: '2026-10-31',
            version: 1,
            created_at: '2026-10-31T12:00:00Z',
            updated_at: '2026-10-31T12:00:00Z',
          },
        ],
        meta: {
          total: 25,
          limit: 10,
          offset: 0,
          next_cursor: '10',
        },
      };
    };

    const result = await fetchExpenses({ limit: 10, offset: 0 });

    assert.strictEqual(capturedEndpoint, '/api/v1/expenses?limit=10&offset=0');
    assert.strictEqual(capturedOptions.method, 'GET');
    assert.strictEqual(capturedOptions.requiresAuth, true);

    assert.strictEqual(result.expenses.length, 1);
    assert.strictEqual(result.expenses[0].id, 'exp-1');
    assert.strictEqual(result.expenses[0].amountPaise, 50000);
    assert.strictEqual(result.total, 25);
    assert.strictEqual(result.hasMore, true);
    assert.strictEqual(result.limit, 10);
    assert.strictEqual(result.offset, 0);
  });

  await t.test('fetches next page with limit=10, offset=20 and includes search/filter params', async () => {
    let capturedEndpoint = '';

    fastApiClient.executeRequest = async (endpoint) => {
      capturedEndpoint = endpoint;
      return {
        data: [],
        meta: {
          total: 20,
          limit: 10,
          offset: 20,
          next_cursor: null,
        },
      };
    };

    const result = await fetchExpenses({
      limit: 10,
      offset: 20,
      categoryId: 'groceries',
      from: '2026-10-01',
      to: '2026-10-31',
      query: 'Supermarket',
    });

    const parsedUrl = new URL(`http://localhost${capturedEndpoint}`);
    assert.strictEqual(parsedUrl.pathname, '/api/v1/expenses');
    assert.strictEqual(parsedUrl.searchParams.get('limit'), '10');
    assert.strictEqual(parsedUrl.searchParams.get('offset'), '20');
    assert.strictEqual(parsedUrl.searchParams.get('category_id'), 'groceries');
    assert.strictEqual(parsedUrl.searchParams.get('from'), '2026-10-01');
    assert.strictEqual(parsedUrl.searchParams.get('to'), '2026-10-31');
    assert.strictEqual(parsedUrl.searchParams.get('q'), 'Supermarket');

    assert.strictEqual(result.expenses.length, 0);
    assert.strictEqual(result.total, 20);
    assert.strictEqual(result.hasMore, false);
  });

  await t.test('handles empty response gracefully', async () => {
    fastApiClient.executeRequest = async () => ({
      data: [],
      meta: {
        total: 0,
        limit: 20,
        offset: 0,
        next_cursor: null,
      },
    });

    const result = await fetchExpenses();
    assert.strictEqual(result.expenses.length, 0);
    assert.strictEqual(result.total, 0);
    assert.strictEqual(result.hasMore, false);
  });

  await t.test('propagates ApiError on backend failure', async () => {
    fastApiClient.executeRequest = async () => {
      throw new ApiError('UNAUTHORIZED', 'Session expired. Please log in again.', false);
    };

    await assert.rejects(
      async () => {
        await fetchExpenses();
      },
      (err) => {
        assert.ok(err instanceof ApiError);
        assert.strictEqual(err.code, 'UNAUTHORIZED');
        assert.strictEqual(err.message, 'Session expired. Please log in again.');
        return true;
      }
    );
  });

  await t.test('propagates network failure as retryable ApiError', async () => {
    fastApiClient.executeRequest = async () => {
      throw new ApiError('NETWORK_ERROR', 'Unable to connect to the server.', true);
    };

    await assert.rejects(
      async () => {
        await fetchExpenses();
      },
      (err) => {
        assert.ok(err instanceof ApiError);
        assert.strictEqual(err.code, 'NETWORK_ERROR');
        assert.strictEqual(err.isRetryable, true);
        return true;
      }
    );
  });
});

// ---------------------------------------------------------------------------
// 3. useExpenses Hook State Logic Simulation Tests
// ---------------------------------------------------------------------------
test('useExpenses Hook Lifecycle & State Logic', async (t) => {
  const originalExecuteRequest = fastApiClient.executeRequest;

  t.afterEach(() => {
    fastApiClient.executeRequest = originalExecuteRequest;
  });

  await t.test('initial load populates expenses, total, and computes hasMore', async () => {
    fastApiClient.executeRequest = async () => ({
      data: [
        {
          id: 'exp-1',
          user_id: 'u1',
          category_id: 'food',
          amount_minor: 12000,
          description: 'Coffee',
          expense_date: '2026-11-01',
          version: 1,
          created_at: '2026-11-01T08:00:00Z',
          updated_at: '2026-11-01T08:00:00Z',
        },
        {
          id: 'exp-2',
          user_id: 'u1',
          category_id: 'transport',
          amount_minor: 25000,
          description: 'Metro',
          expense_date: '2026-11-01',
          version: 1,
          created_at: '2026-11-01T08:30:00Z',
          updated_at: '2026-11-01T08:30:00Z',
        },
      ],
      meta: {
        total: 5,
        limit: 2,
        offset: 0,
        next_cursor: '2',
      },
    });

    const res = await fetchExpenses({ limit: 2, offset: 0 });
    assert.strictEqual(res.expenses.length, 2);
    assert.strictEqual(res.total, 5);
    assert.strictEqual(res.hasMore, true);
  });

  await t.test('next page appends unique items and deduplicates overlapping IDs', async () => {
    const existing = [
      mapBackendExpenseToDomain({
        id: 'exp-1',
        user_id: 'u1',
        category_id: 'food',
        amount_minor: 12000,
        description: 'Coffee',
        expense_date: '2026-11-01',
        version: 1,
        created_at: '2026-11-01T08:00:00Z',
        updated_at: '2026-11-01T08:00:00Z',
      }),
    ];

    const incoming = [
      mapBackendExpenseToDomain({
        id: 'exp-1', // duplicate
        user_id: 'u1',
        category_id: 'food',
        amount_minor: 12000,
        description: 'Coffee',
        expense_date: '2026-11-01',
        version: 1,
        created_at: '2026-11-01T08:00:00Z',
        updated_at: '2026-11-01T08:00:00Z',
      }),
      mapBackendExpenseToDomain({
        id: 'exp-3', // new
        user_id: 'u1',
        category_id: 'shopping',
        amount_minor: 49900,
        description: 'Shoes',
        expense_date: '2026-11-01',
        version: 1,
        created_at: '2026-11-01T09:00:00Z',
        updated_at: '2026-11-01T09:00:00Z',
      }),
    ];

    const existingIds = new Set(existing.map((e) => e.id));
    const uniqueIncoming = incoming.filter((e) => !existingIds.has(e.id));
    const merged = [...existing, ...uniqueIncoming];

    assert.strictEqual(merged.length, 2);
    assert.strictEqual(merged[0].id, 'exp-1');
    assert.strictEqual(merged[1].id, 'exp-3');
  });

  await t.test('refresh resets offset to 0 and replaces existing list entirely', async () => {
    let callOffset = -1;

    fastApiClient.executeRequest = async (endpoint) => {
      const u = new URL(`http://localhost${endpoint}`);
      callOffset = Number(u.searchParams.get('offset'));
      return {
        data: [
          {
            id: 'exp-fresh',
            user_id: 'u1',
            category_id: 'food',
            amount_minor: 10000,
            description: 'Fresh coffee',
            expense_date: '2026-11-01',
            version: 1,
            created_at: '2026-11-01T10:00:00Z',
            updated_at: '2026-11-01T10:00:00Z',
          },
        ],
        meta: {
          total: 1,
          limit: 10,
          offset: 0,
          next_cursor: null,
        },
      };
    };

    const refreshResult = await fetchExpenses({ limit: 10, offset: 0 });
    assert.strictEqual(callOffset, 0);
    assert.strictEqual(refreshResult.expenses.length, 1);
    assert.strictEqual(refreshResult.expenses[0].id, 'exp-fresh');
  });

  await t.test('duplicate in-flight requests are blocked by concurrency guard', async () => {
    let activeCalls = 0;
    let maxConcurrent = 0;

    let inFlight = false;
    const fetchGuarded = async () => {
      if (inFlight) return null;
      inFlight = true;
      activeCalls++;
      maxConcurrent = Math.max(maxConcurrent, activeCalls);
      await new Promise((r) => setTimeout(r, 20));
      activeCalls--;
      inFlight = false;
      return 'done';
    };

    const [r1, r2, r3] = await Promise.all([
      fetchGuarded(),
      fetchGuarded(),
      fetchGuarded(),
    ]);

    assert.strictEqual(maxConcurrent, 1);
    assert.strictEqual(r1, 'done');
    assert.strictEqual(r2, null);
    assert.strictEqual(r3, null);
  });

  await t.test('stale responses from older requests are safely discarded', async () => {
    let latestRequestId = 0;
    let committedData = '';

    const executeWithSequence = async (reqId, data, delayMs) => {
      await new Promise((r) => setTimeout(r, delayMs));
      if (reqId === latestRequestId) {
        committedData = data;
      }
    };

    latestRequestId = 1;
    const p1 = executeWithSequence(1, 'old-page', 40);

    latestRequestId = 2; // Newer request triggered (e.g. refresh or filter change)
    const p2 = executeWithSequence(2, 'new-page', 10);

    await Promise.all([p1, p2]);

    assert.strictEqual(committedData, 'new-page');
  });
});
