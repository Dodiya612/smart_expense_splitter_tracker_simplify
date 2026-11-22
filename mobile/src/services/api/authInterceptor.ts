import { API_TIMEOUT_MS, resolveApiBaseUrl } from '../../constants/apiConfig';
import { tokenStorage } from '../auth/tokenStorage';
import { ApiError, type TokenBundle } from './types';

type AuthFailureListener = () => void;
const authFailureListeners = new Set<AuthFailureListener>();

/**
 * Registers a listener called when authentication fails irreversibly
 * (e.g. refresh token expired or revoked), triggering a clean logout.
 */
export function registerAuthFailureListener(listener: AuthFailureListener): () => void {
  authFailureListeners.add(listener);
  return () => {
    authFailureListeners.delete(listener);
  };
}

export function notifyAuthFailure(): void {
  authFailureListeners.forEach((listener) => {
    try {
      listener();
    } catch {
      // Ignore listener error
    }
  });
}

/**
 * Single-flight promise mutex for refresh token rotation.
 * All concurrent 401 responses wait on the exact same in-flight promise,
 * preventing duplicate refresh requests that would trigger token reuse invalidation.
 */
let refreshPromise: Promise<string> | null = null;

/** True while runWithRefreshLock holds the single-flight slot; counts callers that waited. */
let lockActive = false;
let lockWaiters = 0;

export async function requestTokenRefresh(): Promise<string> {
  if (refreshPromise) {
    if (lockActive) lockWaiters += 1;
    return refreshPromise;
  }

  refreshPromise = (async () => {
    const currentRefreshToken = await tokenStorage.getRefreshToken();
    if (!currentRefreshToken) {
      await tokenStorage.clearAll();
      notifyAuthFailure();
      throw new ApiError(
        'UNAUTHORIZED',
        'Session expired. Please log in again.',
        false
      );
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);

    try {
      let response: Response;
      try {
        response = await fetch(`${resolveApiBaseUrl()}/api/v1/auth/refresh`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify({ refreshToken: currentRefreshToken }),
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timeoutId);
      }

      if (!response.ok) {
        let errorCode = response.status >= 500 ? 'INTERNAL_SERVER_ERROR' : 'REFRESH_FAILED';
        let errorMessage = response.status >= 500
          ? 'Authentication server error. Please try again later.'
          : 'Session expired. Please log in again.';
        let isRetryable = response.status >= 500 || response.status === 429;

        try {
          const errorBody = await response.json();
          if (errorBody && typeof errorBody === 'object') {
            errorCode = errorBody.code || errorCode;
            errorMessage = errorBody.message || errorMessage;
            if (typeof errorBody.isRetryable === 'boolean') {
              isRetryable = errorBody.isRetryable;
            }
          }
        } catch {
          // Fall back to default message
        }

        // Only clear tokens and notify auth failure listeners on DEFINITIVE auth rejection
        // (e.g. 401 Unauthorized, 403 Forbidden, or explicit non-retryable 4xx rejection).
        // Temporary server errors (5xx) and rate limits (429) must NOT wipe stored session tokens.
        const isDefinitiveAuthFailure =
          response.status === 401 ||
          response.status === 403 ||
          (!isRetryable && response.status < 500 && response.status !== 429);

        if (isDefinitiveAuthFailure) {
          await tokenStorage.clearAll();
          notifyAuthFailure();
        }

        throw new ApiError(errorCode, errorMessage, isRetryable);
      }

      const data = await response.json();
      const tokens: TokenBundle = {
        accessToken: data.accessToken,
        refreshToken: data.refreshToken,
        tokenType: data.tokenType ?? 'bearer',
        expiresIn: data.expiresIn ?? 900,
      };

      await tokenStorage.saveTokens(tokens);
      return tokens.accessToken;
    } catch (err) {
      if (err instanceof ApiError) {
        throw err;
      }
      if (err instanceof Error && err.name === 'AbortError') {
        throw new ApiError(
          'REQUEST_TIMEOUT',
          'Refresh request timed out. Please try again.',
          true
        );
      }
      // If network error during refresh
      throw new ApiError(
        'NETWORK_ERROR',
        'Unable to connect to authentication server.',
        true
      );
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Runs `task` while holding the refresh single-flight slot (T-50, change password).
 *
 * The task replaces this device's tokens on the server (the refresh token is rotated).
 * If another request hit a 401 meanwhile and refreshed with the stored, now-replaced
 * refresh token, the server would treat it as token reuse and sign this device out.
 * Holding the slot makes such requests wait; once the task has stored the new tokens they
 * continue with the new access token. If the task fails, waiting requests get a normal
 * refresh instead.
 *
 * The task itself must not call requestTokenRefresh (it would wait on itself).
 */
export async function runWithRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  // Let a refresh (or another locked task) that is already running finish first.
  while (refreshPromise) {
    try {
      await refreshPromise;
    } catch {
      // Its own caller handles that failure.
    }
  }

  let resolveGate: (token: string) => void = () => undefined;
  let rejectGate: (err: unknown) => void = () => undefined;
  const gate = new Promise<string>((resolve, reject) => {
    resolveGate = resolve;
    rejectGate = reject;
  });
  gate.catch(() => undefined); // nobody may be waiting; never an unhandled rejection
  refreshPromise = gate;
  lockActive = true;
  lockWaiters = 0;

  let succeeded = false;
  try {
    const result = await task();
    succeeded = true;
    return result;
  } finally {
    const waiters = lockWaiters;
    lockActive = false;
    lockWaiters = 0;
    refreshPromise = null;
    const stored = succeeded ? await tokenStorage.getAccessToken() : null;
    if (stored) {
      resolveGate(stored);
    } else if (waiters > 0) {
      requestTokenRefresh().then(resolveGate, rejectGate);
    } else {
      rejectGate(new ApiError('SESSION_EXPIRED', 'Session expired. Please log in again.', false));
    }
  }
}

/**
 * Resets the single-flight refresh state (used primarily in tests).
 */
export function _resetRefreshMutex(): void {
  refreshPromise = null;
  lockActive = false;
  lockWaiters = 0;
}
