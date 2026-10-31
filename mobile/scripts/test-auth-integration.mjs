import test from 'node:test';
import assert from 'node:assert';

// ---------------------------------------------------------------------------
// 1. ApiError and Error Handling Tests
// ---------------------------------------------------------------------------
import { ApiError } from '../src/services/api/types.ts';

test('ApiError Data Structure & Contract Compliance', async (t) => {
  await t.test('creates standard ApiError with code, message, and isRetryable', () => {
    const err = new ApiError('INVALID_CREDENTIALS', 'Invalid email or password.', false);
    assert.strictEqual(err.name, 'ApiError');
    assert.strictEqual(err.code, 'INVALID_CREDENTIALS');
    assert.strictEqual(err.message, 'Invalid email or password.');
    assert.strictEqual(err.isRetryable, false);
    assert.strictEqual(err.detail, null);
  });

  await t.test('handles validation error envelope with detail array', () => {
    const details = [{ loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' }];
    const err = new ApiError('VALIDATION_ERROR', 'Invalid request parameters.', false, details);
    assert.strictEqual(err.code, 'VALIDATION_ERROR');
    assert.deepStrictEqual(err.detail, details);
  });

  await t.test('gracefully handles missing, null, or undefined detail without throwing', () => {
    const err1 = new ApiError('NOT_FOUND', 'User not found', false, null);
    const err2 = new ApiError('SERVER_ERROR', 'Internal error', true);
    assert.strictEqual(err1.detail, null);
    assert.strictEqual(err2.detail, null);
  });

});

// ---------------------------------------------------------------------------
// 2. Token Storage Tests (In-Memory / Web Fallback Engine)
// ---------------------------------------------------------------------------
import { tokenStorage } from '../src/services/auth/tokenStorage.ts';

test('tokenStorage Service', async (t) => {
  await t.test('saves and retrieves access and refresh tokens', async () => {
    await tokenStorage.clearAll();

    assert.strictEqual(await tokenStorage.getAccessToken(), null);
    assert.strictEqual(await tokenStorage.getRefreshToken(), null);

    await tokenStorage.saveTokens({
      accessToken: 'test_access_jwt_123',
      refreshToken: 'test_refresh_hex_456',
      tokenType: 'bearer',
      expiresIn: 900,
    });

    assert.strictEqual(await tokenStorage.getAccessToken(), 'test_access_jwt_123');
    assert.strictEqual(await tokenStorage.getRefreshToken(), 'test_refresh_hex_456');
  });

  await t.test('saves and retrieves cached user profile', async () => {
    const dummyUser = { id: 'usr_abc', name: 'Aarav Sharma', email: 'aarav@example.in' };
    await tokenStorage.saveUser(dummyUser);

    const retrieved = await tokenStorage.getUser();
    assert.deepStrictEqual(retrieved, dummyUser);
  });

  await t.test('clearAll removes tokens and cached user data', async () => {
    await tokenStorage.clearAll();
    assert.strictEqual(await tokenStorage.getAccessToken(), null);
    assert.strictEqual(await tokenStorage.getRefreshToken(), null);
    assert.strictEqual(await tokenStorage.getUser(), null);
  });
});

// ---------------------------------------------------------------------------
// 3. API URL Resolution Tests
// ---------------------------------------------------------------------------
import { configureApiRuntime, resolveApiBaseUrl } from '../src/constants/apiConfig.ts';

test('resolveApiBaseUrl Host Resolution', async (t) => {
  const originalEnv = process.env.EXPO_PUBLIC_API_URL;

  await t.test('honors EXPO_PUBLIC_API_URL environment override with trailing slash stripping', () => {
    process.env.EXPO_PUBLIC_API_URL = 'https://api.splittr.dev/v1///';
    const resolved = resolveApiBaseUrl();
    assert.strictEqual(resolved, 'https://api.splittr.dev/v1');
    process.env.EXPO_PUBLIC_API_URL = originalEnv;
  });

  await t.test('derives Metro host IP when running in development with hostUri', () => {
    delete process.env.EXPO_PUBLIC_API_URL;
    configureApiRuntime({
      isDev: true,
      hostUri: '192.168.1.42:8081',
      platformOs: 'ios',
    });

    const resolved = resolveApiBaseUrl();
    assert.strictEqual(resolved, 'http://192.168.1.42:8000');
    process.env.EXPO_PUBLIC_API_URL = originalEnv;
  });

  await t.test('falls back to 10.0.2.2:8000 on Android emulator when hostUri is absent', () => {
    delete process.env.EXPO_PUBLIC_API_URL;
    configureApiRuntime({
      isDev: false,
      hostUri: null,
      platformOs: 'android',
    });

    const resolved = resolveApiBaseUrl();
    assert.strictEqual(resolved, 'http://10.0.2.2:8000');
    process.env.EXPO_PUBLIC_API_URL = originalEnv;
  });

  await t.test('falls back to localhost:8000 on iOS / Web when hostUri is absent', () => {
    delete process.env.EXPO_PUBLIC_API_URL;
    configureApiRuntime({
      isDev: false,
      hostUri: null,
      platformOs: 'ios',
    });

    const resolved = resolveApiBaseUrl();
    assert.strictEqual(resolved, 'http://localhost:8000');
    process.env.EXPO_PUBLIC_API_URL = originalEnv;
  });
});


// ---------------------------------------------------------------------------
// 4. Single-Flight Refresh Concurrency & Mutex Tests
// ---------------------------------------------------------------------------
import {
  requestTokenRefresh,
  registerAuthFailureListener,
  _resetRefreshMutex,
} from '../src/services/api/authInterceptor.ts';

test('Single-Flight Refresh Mutex and Concurrency', async (t) => {
  const originalFetch = globalThis.fetch;

  await t.test('multiple concurrent 401 callers trigger exactly ONE refresh request', async () => {
    _resetRefreshMutex();
    await tokenStorage.saveTokens({
      accessToken: 'expired_access_token',
      refreshToken: 'valid_refresh_token_789',
    });

    let networkCallCount = 0;
    globalThis.fetch = async (url, options) => {
      networkCallCount++;
      // Simulate network delay
      await new Promise((resolve) => setTimeout(resolve, 50));
      return {
        ok: true,
        status: 200,
        json: async () => ({
          accessToken: 'freshly_minted_access_jwt',
          refreshToken: 'rotated_refresh_hex',
          tokenType: 'bearer',
          expiresIn: 900,
        }),
      };
    };

    try {
      // Dispatch 4 concurrent refresh requests simultaneously
      const results = await Promise.all([
        requestTokenRefresh(),
        requestTokenRefresh(),
        requestTokenRefresh(),
        requestTokenRefresh(),
      ]);

      // Exactly ONE network request must have been dispatched
      assert.strictEqual(networkCallCount, 1, 'Only one refresh HTTP call must be made');

      // All 4 callers must receive the exact same new access token
      results.forEach((token) => {
        assert.strictEqual(token, 'freshly_minted_access_jwt');
      });

      // Storage must be updated with the rotated tokens
      assert.strictEqual(await tokenStorage.getAccessToken(), 'freshly_minted_access_jwt');
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'rotated_refresh_hex');
    } finally {
      globalThis.fetch = originalFetch;
      _resetRefreshMutex();
    }
  });

  await t.test('refresh rejection clears storage and notifies auth failure listener', async () => {
    _resetRefreshMutex();
    await tokenStorage.saveTokens({
      accessToken: 'expired_access_token',
      refreshToken: 'revoked_refresh_token',
    });

    let listenerFired = false;
    const unregister = registerAuthFailureListener(() => {
      listenerFired = true;
    });

    globalThis.fetch = async () => ({
      ok: false,
      status: 401,
      json: async () => ({
        code: 'TOKEN_REVOKED',
        message: 'Refresh token has been revoked.',
        detail: null,
        isRetryable: false,
      }),
    });

    try {
      await assert.rejects(
        async () => {
          await requestTokenRefresh();
        },
        (err) => {
          assert.strictEqual(err.code, 'TOKEN_REVOKED');
          return true;
        }
      );

      assert.strictEqual(listenerFired, true, 'Auth failure listener must be notified');
      assert.strictEqual(await tokenStorage.getAccessToken(), null, 'Access token must be cleared');
      assert.strictEqual(await tokenStorage.getRefreshToken(), null, 'Refresh token must be cleared');
    } finally {
      unregister();
      globalThis.fetch = originalFetch;
      _resetRefreshMutex();
    }
  });
});

// ---------------------------------------------------------------------------
// 5. FastApiClient & Wire Contract Verification
// ---------------------------------------------------------------------------
import { FastApiClient } from '../src/services/api/fastApiClient.ts';

test('FastApiClient Wire Format & Header Compliance', async (t) => {
  const originalFetch = globalThis.fetch;
  const client = new FastApiClient('http://test-server:8000');

  await t.test('login dispatches valid camelCase payload and persists token bundle', async () => {
    await tokenStorage.clearAll();

    let capturedUrl = '';
    let capturedBody = null;

    globalThis.fetch = async (url, options) => {
      capturedUrl = url;
      capturedBody = JSON.parse(options.body);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          user: { id: 'usr_test_1', name: 'Priya Patel', email: 'priya@example.in' },
          tokens: {
            accessToken: 'jwt_access_login',
            refreshToken: 'refresh_hex_login',
            tokenType: 'bearer',
            expiresIn: 900,
          },
        }),
      };
    };

    try {
      const res = await client.login({
        email: '  Priya@Example.in  ',
        password: 'ValidPassword123!',
      });

      assert.strictEqual(capturedUrl, 'http://test-server:8000/api/v1/auth/login');
      assert.strictEqual(capturedBody.email, 'Priya@Example.in');
      assert.strictEqual(capturedBody.password, 'ValidPassword123!');
      assert.strictEqual(res.user.email, 'priya@example.in');
      assert.strictEqual(await tokenStorage.getAccessToken(), 'jwt_access_login');
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'refresh_hex_login');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('signup dispatches name, email, password matching backend schema', async () => {
    await tokenStorage.clearAll();

    let capturedBody = null;
    globalThis.fetch = async (url, options) => {
      capturedBody = JSON.parse(options.body);
      return {
        ok: true,
        status: 201,
        json: async () => ({
          user: { id: 'usr_test_2', name: 'Rohan Verma', email: 'rohan@example.in' },
          tokens: {
            accessToken: 'jwt_signup',
            refreshToken: 'refresh_signup',
          },
        }),
      };
    };

    try {
      await client.signup({
        name: '  Rohan Verma  ',
        email: 'rohan@example.in',
        password: 'Password999!',
      });

      assert.strictEqual(capturedBody.name, 'Rohan Verma');
      assert.strictEqual(capturedBody.email, 'rohan@example.in');
      assert.strictEqual(capturedBody.password, 'Password999!');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('me attaches Authorization: Bearer header', async () => {
    await tokenStorage.saveTokens({
      accessToken: 'authenticated_bearer_token',
      refreshToken: 'dummy_refresh',
    });

    let capturedAuthHeader = '';
    globalThis.fetch = async (url, options) => {
      capturedAuthHeader = options.headers.Authorization;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: 'usr_me',
          name: 'Me User',
          email: 'me@example.in',
        }),
      };
    };

    try {
      const user = await client.me();
      assert.strictEqual(capturedAuthHeader, 'Bearer authenticated_bearer_token');
      assert.strictEqual(user.id, 'usr_me');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('logout sends body and header, then clears local storage', async () => {
    await tokenStorage.saveTokens({
      accessToken: 'logout_bearer_token',
      refreshToken: 'logout_refresh_token',
    });

    let logoutPayload = null;
    let logoutHeader = null;
    globalThis.fetch = async (url, options) => {
      logoutHeader = options.headers.Authorization;
      logoutPayload = JSON.parse(options.body);
      return {
        ok: true,
        status: 200,
        json: async () => ({ message: 'Successfully logged out.' }),
      };
    };

    try {
      await client.logout();
      assert.strictEqual(logoutHeader, 'Bearer logout_bearer_token');
      assert.strictEqual(logoutPayload.refreshToken, 'logout_refresh_token');
      assert.strictEqual(await tokenStorage.getAccessToken(), null);
      assert.strictEqual(await tokenStorage.getRefreshToken(), null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('handles 422 validation error with loc and msg without throwing syntax error', async () => {
    globalThis.fetch = async () => ({
      ok: false,
      status: 422,
      json: async () => ({
        code: 'VALIDATION_ERROR',
        message: 'Invalid request parameters.',
        detail: [{ loc: ['body', 'password'], msg: 'password must be at least 8 characters', type: 'value_error' }],
        isRetryable: false,
      }),
    });

    try {
      await assert.rejects(
        async () => {
          await client.login({ email: 'test@example.in', password: '1' });
        },
        (err) => {
          assert.strictEqual(err.code, 'VALIDATION_ERROR');
          assert.ok(Array.isArray(err.detail));
          assert.strictEqual(err.detail[0].loc[1], 'password');
          return true;
        }
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});

// ---------------------------------------------------------------------------
// 6. Session Restoration & Resilient Error Handling Tests
// ---------------------------------------------------------------------------
test('Session Restoration & Resilient Error Handling', async (t) => {
  const originalFetch = globalThis.fetch;
  const client = new FastApiClient('http://test-server:8000');

  // Helper modeling the exact session restoration logic implemented in AuthContext
  async function simulateRestoreSession() {
    let restoredUser = null;
    let isSessionValid = false;

    const [cachedUser, refreshToken] = await Promise.all([
      tokenStorage.getUser(),
      tokenStorage.getRefreshToken(),
    ]);

    if (!refreshToken) {
      return { user: null, isAuthenticated: false };
    }

    if (cachedUser) {
      restoredUser = cachedUser;
    }

    try {
      const freshUser = await client.me();
      restoredUser = freshUser;
      await tokenStorage.saveUser(freshUser);
      isSessionValid = true;
    } catch (err) {
      const isTransient =
        err instanceof ApiError
          ? err.isRetryable
          : err instanceof Error &&
            (err.name === 'AbortError' ||
              err.message.toLowerCase().includes('network') ||
              err.message.toLowerCase().includes('fetch'));

      if (!isTransient) {
        restoredUser = null;
        await tokenStorage.clearAll();
        isSessionValid = false;
      } else {
        // Transient error preserves existing session and cached profile
        isSessionValid = Boolean(cachedUser);
      }
    }

    return { user: restoredUser, isAuthenticated: isSessionValid };
  }

  await t.test('1. Valid session restoration fetches fresh profile and updates cache', async () => {
    await tokenStorage.clearAll();
    await tokenStorage.saveTokens({
      accessToken: 'valid_access_token_111',
      refreshToken: 'valid_refresh_token_222',
    });
    await tokenStorage.saveUser({
      id: 'usr_cold_start',
      name: 'Initial Name',
      email: 'coldstart@example.in',
    });

    globalThis.fetch = async (url, options) => {
      assert.strictEqual(options.headers.Authorization, 'Bearer valid_access_token_111');
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: 'usr_cold_start',
          name: 'Updated Server Name',
          email: 'coldstart@example.in',
        }),
      };
    };

    try {
      const result = await simulateRestoreSession();
      assert.strictEqual(result.isAuthenticated, true);
      assert.strictEqual(result.user.name, 'Updated Server Name');

      const cachedUser = await tokenStorage.getUser();
      assert.strictEqual(cachedUser.name, 'Updated Server Name');
      assert.strictEqual(await tokenStorage.getAccessToken(), 'valid_access_token_111');
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'valid_refresh_token_222');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('2. Expired/revoked refresh token clears storage and notifies auth failure listener', async () => {
    await tokenStorage.clearAll();
    _resetRefreshMutex();

    await tokenStorage.saveTokens({
      accessToken: 'expired_access_token_333',
      refreshToken: 'revoked_refresh_token_444',
    });
    await tokenStorage.saveUser({
      id: 'usr_revoked',
      name: 'Revoked User',
      email: 'revoked@example.in',
    });

    let authFailureNotified = false;
    const unregister = registerAuthFailureListener(() => {
      authFailureNotified = true;
    });

    globalThis.fetch = async (url) => {
      if (url.includes('/api/v1/auth/me')) {
        return {
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          json: async () => ({ code: 'UNAUTHORIZED', message: 'Token expired', isRetryable: false }),
        };
      }
      if (url.includes('/api/v1/auth/refresh')) {
        return {
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          json: async () => ({
            code: 'TOKEN_REVOKED',
            message: 'Refresh token has been revoked.',
            isRetryable: false,
          }),
        };
      }
      throw new Error(`Unexpected endpoint: ${url}`);
    };

    try {
      const result = await simulateRestoreSession();
      assert.strictEqual(result.isAuthenticated, false);
      assert.strictEqual(result.user, null);
      assert.strictEqual(authFailureNotified, true, 'Auth failure listener must have fired');
      assert.strictEqual(await tokenStorage.getAccessToken(), null, 'Tokens must be cleared');
      assert.strictEqual(await tokenStorage.getRefreshToken(), null, 'Tokens must be cleared');
      assert.strictEqual(await tokenStorage.getUser(), null, 'Cached user must be cleared');
    } finally {
      unregister();
      globalThis.fetch = originalFetch;
      _resetRefreshMutex();
    }
  });

  await t.test('3. Network failure during session restoration preserves cached session and tokens', async () => {
    await tokenStorage.clearAll();
    await tokenStorage.saveTokens({
      accessToken: 'offline_access_token',
      refreshToken: 'offline_refresh_token',
    });
    const cachedProfile = {
      id: 'usr_offline',
      name: 'Offline User',
      email: 'offline@example.in',
    };
    await tokenStorage.saveUser(cachedProfile);

    let authFailureNotified = false;
    const unregister = registerAuthFailureListener(() => {
      authFailureNotified = true;
    });

    // Simulate complete network failure (TypeError from fetch)
    globalThis.fetch = async () => {
      throw new TypeError('Failed to fetch (network disconnected)');
    };

    try {
      const result = await simulateRestoreSession();
      // Should preserve user and stay authenticated in offline mode
      assert.strictEqual(result.isAuthenticated, true);
      assert.deepStrictEqual(result.user, cachedProfile);
      assert.strictEqual(authFailureNotified, false, 'Auth failure must NOT be notified on transient network error');

      // Tokens and cached profile must remain in storage
      assert.strictEqual(await tokenStorage.getAccessToken(), 'offline_access_token');
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'offline_refresh_token');
      assert.deepStrictEqual(await tokenStorage.getUser(), cachedProfile);
    } finally {
      unregister();
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('4. Backend 5xx during refresh preserves stored tokens without auth failure notification', async () => {
    await tokenStorage.clearAll();
    _resetRefreshMutex();

    await tokenStorage.saveTokens({
      accessToken: 'expired_access_for_500',
      refreshToken: 'valid_refresh_token_survives',
    });

    let authFailureNotified = false;
    const unregister = registerAuthFailureListener(() => {
      authFailureNotified = true;
    });

    // /me triggers 401, which triggers /refresh, which returns 500
    globalThis.fetch = async (url) => {
      if (url.includes('/api/v1/auth/me')) {
        return {
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          json: async () => ({ code: 'UNAUTHORIZED', message: 'Token expired' }),
        };
      }
      if (url.includes('/api/v1/auth/refresh')) {
        return {
          ok: false,
          status: 500,
          statusText: 'Internal Server Error',
          json: async () => ({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Database temporarily unavailable',
            isRetryable: true,
          }),
        };
      }
      throw new Error(`Unexpected endpoint: ${url}`);
    };

    try {
      await assert.rejects(
        async () => {
          await client.me();
        },
        (err) => {
          assert.strictEqual(err.code, 'INTERNAL_SERVER_ERROR');
          assert.strictEqual(err.isRetryable, true, '500 error must be flagged as retryable');
          return true;
        }
      );

      assert.strictEqual(authFailureNotified, false, 'Auth failure listener must NOT fire on server 5xx');
      assert.strictEqual(
        await tokenStorage.getRefreshToken(),
        'valid_refresh_token_survives',
        'Refresh token must remain stored on server 5xx'
      );
    } finally {
      unregister();
      globalThis.fetch = originalFetch;
      _resetRefreshMutex();
    }
  });

  await t.test('5. Successful refresh after a temporary failure recovers and rotates tokens', async () => {
    await tokenStorage.clearAll();
    _resetRefreshMutex();

    await tokenStorage.saveTokens({
      accessToken: 'expired_token_retry',
      refreshToken: 'refresh_token_retry',
    });

    let attemptCount = 0;
    globalThis.fetch = async (url) => {
      if (url.includes('/api/v1/auth/refresh')) {
        attemptCount++;
        if (attemptCount === 1) {
          // Attempt 1: Transient 503 error
          return {
            ok: false,
            status: 503,
            statusText: 'Service Unavailable',
            json: async () => ({
              code: 'SERVICE_UNAVAILABLE',
              message: 'Server undergoing maintenance',
              isRetryable: true,
            }),
          };
        }
        // Attempt 2: Server recovered!
        return {
          ok: true,
          status: 200,
          json: async () => ({
            accessToken: 'recovered_fresh_access_token',
            refreshToken: 'recovered_fresh_refresh_token',
            tokenType: 'bearer',
            expiresIn: 900,
          }),
        };
      }
      throw new Error(`Unexpected endpoint: ${url}`);
    };

    try {
      // First attempt: should fail with retryable error, tokens preserved
      await assert.rejects(
        async () => {
          await requestTokenRefresh();
        },
        (err) => {
          assert.strictEqual(err.isRetryable, true);
          return true;
        }
      );
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'refresh_token_retry');

      // Second attempt: succeeds and rotates tokens
      const newAccessToken = await requestTokenRefresh();
      assert.strictEqual(newAccessToken, 'recovered_fresh_access_token');
      assert.strictEqual(await tokenStorage.getAccessToken(), 'recovered_fresh_access_token');
      assert.strictEqual(await tokenStorage.getRefreshToken(), 'recovered_fresh_refresh_token');
    } finally {
      globalThis.fetch = originalFetch;
      _resetRefreshMutex();
    }
  });
});
