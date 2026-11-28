import http from 'k6/http';
import { check, sleep, group } from 'k6';

/**
 * Coinscious Load and Scalability Benchmark (US-35 / T-61).
 *
 * Simulates 50 concurrent virtual users exercising the core API endpoints
 * to verify response latency meets the NFR-06 / NFR-07 requirement:
 * p95 latency must be strictly under 500 ms at 50 virtual users.
 *
 * Execution:
 *   k6 run tests/load/k6_load_test.js
 *   k6 run -e BASE_URL=https://your-api.onrender.com tests/load/k6_load_test.js
 */

export const options = {
  scenarios: {
    load_50_vus: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '15s', target: 20 }, // Ramp up to 20 VUs
        { duration: '20s', target: 50 }, // Ramp up to 50 VUs
        { duration: '1m', target: 50 },  // Sustain 50 concurrent virtual users
        { duration: '15s', target: 0 },  // Ramp down to 0
      ],
      gracefulRampDown: '5s',
    },
  },
  thresholds: {
    // US-35 acceptance criterion: p95 response time must be under 500 ms
    http_req_duration: ['p(95)<500'],
    // Availability requirement: error rate must not exceed 1%
    http_req_failed: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const TEST_EMAIL = __ENV.TEST_EMAIL || 'user1@example.com';
const TEST_PASSWORD = __ENV.TEST_PASSWORD || 'Password123!';

export function setup() {
  // Pre-flight check and login to acquire access token
  const healthRes = http.get(`${BASE_URL}/api/v1/health`);
  check(healthRes, {
    'health check status is 200': (r) => r.status === 200,
    'database is connected': (r) => {
      try {
        return r.json().database === 'connected';
      } catch (e) {
        return false;
      }
    },
  });

  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: TEST_EMAIL, password: TEST_PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } }
  );

  let token = null;
  if (loginRes.status === 200) {
    try {
      token = loginRes.json().tokens.access_token || loginRes.json().tokens.accessToken;
    } catch (e) {
      token = null;
    }
  }

  return { token: token };
}

export default function (data) {
  const headers = {
    'Content-Type': 'application/json',
    ...(data.token ? { Authorization: `Bearer ${data.token}` } : {}),
  };

  // 1. Health & Maintenance Check Endpoint
  group('01_HealthCheck', () => {
    const res = http.get(`${BASE_URL}/api/v1/health`);
    check(res, {
      'health HTTP 200': (r) => r.status === 200,
    });
  });

  // 2. Personal Expenses List with Keyset Pagination
  group('02_ListExpensesKeyset', () => {
    const res = http.get(`${BASE_URL}/api/v1/expenses?limit=20`, { headers });
    check(res, {
      'expenses list HTTP 200': (r) => r.status === 200,
      'expenses list has data': (r) => {
        try {
          return Array.isArray(r.json().data);
        } catch (e) {
          return false;
        }
      },
    });

    // If nextCursor returned, simulate keyset seek
    try {
      const json = res.json();
      if (json.meta && json.meta.nextCursor) {
        const nextRes = http.get(
          `${BASE_URL}/api/v1/expenses?limit=20&cursor=${json.meta.nextCursor}`,
          { headers }
        );
        check(nextRes, {
          'keyset page 2 HTTP 200': (r) => r.status === 200,
        });
      }
    } catch (e) {
      // Ignored in benchmark
    }
  });

  // 3. Filtered Expenses with Trigram Search & Date Range
  group('03_FilterAndSearchExpenses', () => {
    const res = http.get(
      `${BASE_URL}/api/v1/expenses?query=food&from_date=2026-01-01&limit=20`,
      { headers }
    );
    check(res, {
      'filter expenses HTTP 200': (r) => r.status === 200,
    });
  });

  // 4. Groups Listing
  group('04_ListGroups', () => {
    const res = http.get(`${BASE_URL}/api/v1/groups`, { headers });
    check(res, {
      'groups list HTTP 200': (r) => r.status === 200,
    });
  });

  // 5. Analytics Total Spending
  group('05_AnalyticsTotalSpending', () => {
    const res = http.get(`${BASE_URL}/api/v1/analytics/total-spending`, { headers });
    check(res, {
      'analytics HTTP 200': (r) => r.status === 200,
    });
  });

  sleep(0.5); // 500ms pacing between user iterations
}

export function teardown(data) {
  // Final validation log
  console.log('k6 load test complete. Target: p95 < 500ms at 50 VUs.');
}
