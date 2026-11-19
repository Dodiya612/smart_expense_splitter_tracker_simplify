import { API_TIMEOUT_MS, resolveApiBaseUrl } from '../../constants/apiConfig';
import { requestTokenRefresh, runWithRefreshLock } from './authInterceptor';
import {
  ApiError,
  type ApiClient,
  type ApiErrorDetail,
  type AuthResponse,
  type AuthUser,
  type ChangePasswordPayload,
  type ChangePasswordResponse,
  type LoginCredentials,
  type LogoutPayload,
  type RefreshTokenPayload,
  type SignupPayload,
  type TokenBundle,
} from './types';

import { tokenStorage } from '../auth/tokenStorage';


interface RequestOptions extends RequestInit {
  requiresAuth?: boolean;
  isRetry?: boolean;
  /** Return a 401 as an ApiError instead of refreshing (used inside runWithRefreshLock). */
  skipAuthRefresh?: boolean;
}

/** 401 codes after which a token refresh and one retry can succeed. */
const REFRESHABLE_AUTH_CODES = new Set([
  'TOKEN_EXPIRED',
  'SESSION_NOT_IDENTIFIED',
  'INVALID_TOKEN',
  'UNAUTHORIZED',
  'TOKEN_REVOKED',
]);

export class FastApiClient implements ApiClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = (baseUrl || resolveApiBaseUrl()).replace(/\/+$/, '');
  }

  /**
   * Internal request executor handling headers, timeouts, error parsing,
   * and single-flight 401 token refresh retries.
   */
  private async executeRequest<T>(
    endpoint: string,
    options: RequestOptions = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
    const headers: Record<string, string> = {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string> | undefined),
    };

    if (options.requiresAuth) {
      const accessToken = await tokenStorage.getAccessToken();
      if (accessToken) {
        headers.Authorization = `Bearer ${accessToken}`;
      }
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);


    let response: Response;
    try {
      response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      });
    } catch (err: unknown) {
      clearTimeout(timeoutId);
      if (err instanceof Error && err.name === 'AbortError') {
        throw new ApiError(
          'REQUEST_TIMEOUT',
          'Request timed out. Please try again.',
          true
        );
      }
      throw new ApiError(
        'NETWORK_ERROR',
        'Unable to connect to the server. Please check your internet connection and try again.',
        true
      );
    } finally {
      clearTimeout(timeoutId);
    }

    // Handle 401 Unauthorized for authenticated endpoints (excluding auth routes like /login or /refresh)
    if (
      response.status === 401 &&
      options.requiresAuth &&
      !options.isRetry &&
      !options.skipAuthRefresh &&
      !endpoint.includes('/auth/login') &&
      !endpoint.includes('/auth/signup') &&
      !endpoint.includes('/auth/refresh')
    ) {
      try {
        const newAccessToken = await requestTokenRefresh();
        // Retry the request exactly once with the refreshed token
        return await this.executeRequest<T>(endpoint, {
          ...options,
          isRetry: true,
          headers: {
            ...options.headers,
            Authorization: `Bearer ${newAccessToken}`,
          },
        });
      } catch (refreshErr) {
        // If refresh fails, let the error propagate
        if (refreshErr instanceof ApiError) {
          throw refreshErr;
        }
        throw new ApiError(
          'SESSION_EXPIRED',
          'Your session has expired. Please log in again.',
          false
        );
      }
    }

    // Process non-2xx responses
    if (!response.ok) {
      let code = response.status >= 500 ? 'INTERNAL_SERVER_ERROR' : 'HTTP_ERROR';
      let message = response.statusText || 'An error occurred processing the request.';
      let detail: ApiErrorDetail[] | null = null;
      let isRetryable = response.status >= 500;

      try {
        const errorBody = await response.json();
        if (errorBody && typeof errorBody === 'object') {
          if (typeof errorBody.code === 'string') {
            code = errorBody.code;
          }
          if (typeof errorBody.message === 'string') {
            message = errorBody.message;
          }
          if (typeof errorBody.isRetryable === 'boolean') {
            isRetryable = errorBody.isRetryable;
          }
          // Do not assume detail is always present or an array
          if (Array.isArray(errorBody.detail)) {
            detail = errorBody.detail;
          } else if (errorBody.detail !== undefined && errorBody.detail !== null) {
            if (typeof errorBody.detail === 'string') {
              message = errorBody.detail;
            }
          }
        }
      } catch {
        // Response was not JSON
      }

      throw new ApiError(code, message, isRetryable, detail);
    }

    // 204 No Content
    if (response.status === 204) {
      return {} as T;
    }

    try {
      return (await response.json()) as T;
    } catch {
      return {} as T;
    }
  }

  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const data = await this.executeRequest<AuthResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        email: credentials.email.trim(),
        password: credentials.password,
      }),
    });

    if (data.tokens) {
      await tokenStorage.saveTokens(data.tokens);
    }
    if (data.user) {
      await tokenStorage.saveUser(data.user);
    }

    return data;
  }

  async signup(payload: SignupPayload): Promise<AuthResponse> {
    const data = await this.executeRequest<AuthResponse>('/api/v1/auth/signup', {
      method: 'POST',
      body: JSON.stringify({
        name: payload.name.trim(),
        email: payload.email.trim(),
        password: payload.password,
      }),
    });

    if (data.tokens) {
      await tokenStorage.saveTokens(data.tokens);
    }
    if (data.user) {
      await tokenStorage.saveUser(data.user);
    }

    return data;
  }

  async refresh(payload: RefreshTokenPayload): Promise<TokenBundle> {
    const data = await this.executeRequest<TokenBundle>('/api/v1/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({
        refreshToken: payload.refreshToken,
      }),
    });

    if (data) {
      await tokenStorage.saveTokens(data);
    }

    return data;
  }

  async logout(
    payload?: LogoutPayload,
    accessToken?: string | null
  ): Promise<void> {
    const refreshToken = payload?.refreshToken ?? (await tokenStorage.getRefreshToken());
    const token = accessToken ?? (await tokenStorage.getAccessToken());

    const headers: Record<string, string> = {};
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    try {
      await this.executeRequest<void>('/api/v1/auth/logout', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          refreshToken: refreshToken ?? undefined,
        }),
      });
    } catch {
      // Logout is best-effort on server; local tokens will always be cleared
    } finally {
      await tokenStorage.clearAll();
    }
  }

  async me(accessToken?: string | null): Promise<AuthUser> {
    const headers: Record<string, string> = {};
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
    }

    return await this.executeRequest<AuthUser>('/api/v1/auth/me', {
      method: 'GET',
      headers,
      requiresAuth: !accessToken,
    });
  }

  async changePassword(payload: ChangePasswordPayload): Promise<ChangePasswordResponse> {
    const body = JSON.stringify({
      currentPassword: payload.currentPassword,
      newPassword: payload.newPassword,
      confirmNewPassword: payload.confirmNewPassword,
    });

    // On success the server invalidates the current access token and rotates the refresh
    // token. The request runs under the refresh lock and the new pair is stored before the
    // lock is released, so no concurrent request can refresh with the replaced token.
    const attempt = () =>
      runWithRefreshLock(async () => {
        const data = await this.executeRequest<ChangePasswordResponse>(
          '/api/v1/auth/change-password',
          { method: 'POST', body, requiresAuth: true, skipAuthRefresh: true }
        );
        if (!data?.tokens?.accessToken || !data.tokens.refreshToken) {
          throw new ApiError(
            'INVALID_RESPONSE',
            'Your password may have changed, but the app could not confirm it. Please log in again.',
            false
          );
        }
        await tokenStorage.saveTokens(data.tokens);
        return data;
      });

    try {
      return await attempt();
    } catch (err) {
      // An expired access token, or one issued before T-50 without a session id: refresh
      // outside the lock, then try exactly once more. If refreshing fails the interceptor
      // signs the user out as usual.
      if (err instanceof ApiError && REFRESHABLE_AUTH_CODES.has(err.code)) {
        await requestTokenRefresh();
        return await attempt();
      }
      throw err;
    }
  }

  async get<T>(endpoint: string): Promise<T> {
    return await this.executeRequest<T>(endpoint, {
      method: 'GET',
      requiresAuth: true,
    });
  }

  async post<T>(
    endpoint: string,
    body?: unknown,
    headers?: Record<string, string>
  ): Promise<T> {
    return await this.executeRequest<T>(endpoint, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
      headers,
      requiresAuth: true,
    });
  }

  async patch<T>(
    endpoint: string,
    body?: unknown,
    headers?: Record<string, string>
  ): Promise<T> {
    return await this.executeRequest<T>(endpoint, {
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
      headers,
      requiresAuth: true,
    });
  }

  async put<T>(
    endpoint: string,
    body?: unknown,
    headers?: Record<string, string>
  ): Promise<T> {
    return await this.executeRequest<T>(endpoint, {
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
      headers,
      requiresAuth: true,
    });
  }

  async delete<T>(
    endpoint: string,
    headers?: Record<string, string>
  ): Promise<T> {
    return await this.executeRequest<T>(endpoint, {
      method: 'DELETE',
      headers,
      requiresAuth: true,
    });
  }
}

export const fastApiClient = new FastApiClient();
