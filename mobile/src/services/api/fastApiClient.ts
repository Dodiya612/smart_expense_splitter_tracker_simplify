import { API_TIMEOUT_MS, resolveApiBaseUrl } from '../../constants/apiConfig';
import { requestTokenRefresh } from './authInterceptor';
import {
  ApiError,
  type ApiClient,
  type ApiErrorDetail,
  type AuthResponse,
  type AuthUser,
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
}

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
}

export const fastApiClient = new FastApiClient();
