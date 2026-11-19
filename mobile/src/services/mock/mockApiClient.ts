import { config } from '@/constants/config';
import {
  ApiClient,
  ApiError,
  AuthResponse,
  ChangePasswordPayload,
  ChangePasswordResponse,
  LoginCredentials,
  SignupPayload,
} from '@/services/api/types';
import { mockBalancesGet, mockBalancesPost } from '@/services/mock/mockBalances';
import {
  mockAddPasswordChangedNotice,
  mockNotificationsGet,
  mockNotificationsPatch,
  mockNotificationsPut,
} from '@/services/mock/mockNotifications';

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Deterministic mock implementation of the ApiClient.
 *
 * Deterministic triggers for testing:
 * - Email containing "network.error" simulates a retryable network drop.
 * - Email containing "invalid" simulates bad credentials (non-retryable).
 * - Email containing "exists" simulates an existing account collision during sign-up.
 * - Change password: current password "wrong" is rejected and "network.error" simulates a
 *   retryable network drop; otherwise it succeeds and adds a password_changed notice.
 */
export class MockApiClient implements ApiClient {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    await sleep(config.mockApiLatencyMs);

    const email = credentials.email.toLowerCase().trim();

    if (email.includes('network.error')) {
      throw new ApiError(
        'NETWORK_ERROR',
        'Unable to connect to the server. Please check your internet connection and try again.',
        true
      );
    }

    if (email.includes('invalid') || credentials.password === 'wrong') {
      throw new ApiError(
        'INVALID_CREDENTIALS',
        'Invalid email or password. Please check your credentials.',
        false
      );
    }

    return {
      user: {
        id: 'usr_mock_1',
        name: 'Aarav Sharma',
        email: credentials.email.trim(),
      },
    };
  }

  async signup(payload: SignupPayload): Promise<AuthResponse> {
    await sleep(config.mockApiLatencyMs);

    const email = payload.email.toLowerCase().trim();

    if (email.includes('network.error')) {
      throw new ApiError(
        'NETWORK_ERROR',
        'Unable to connect to the server. Please check your internet connection and try again.',
        true
      );
    }

    if (email.includes('exists')) {
      throw new ApiError(
        'EMAIL_ALREADY_EXISTS',
        'An account with this email already exists. Please log in instead.',
        false
      );
    }

    return {
      user: {
        id: 'usr_mock_2',
        name: payload.name.trim() || 'New User',
        email: payload.email.trim(),
      },
    };
  }

  async refresh(_payload: { refreshToken: string }) {
    await sleep(config.mockApiLatencyMs);
    return {
      accessToken: 'mock_jwt_access_token',
      refreshToken: 'mock_refresh_token',
      tokenType: 'bearer',
      expiresIn: 900,
    };
  }

  async logout(_payload?: { refreshToken?: string }, _accessToken?: string | null): Promise<void> {
    await sleep(config.mockApiLatencyMs);
  }

  async me(_accessToken?: string | null) {
    await sleep(config.mockApiLatencyMs);
    return {
      id: 'usr_mock_1',
      name: 'Aarav Sharma',
      email: 'aarav.sharma@example.in',
    };
  }

  async changePassword(payload: ChangePasswordPayload): Promise<ChangePasswordResponse> {
    await sleep(config.mockApiLatencyMs);
    if (payload.currentPassword === 'network.error') {
      throw new ApiError(
        'NETWORK_ERROR',
        'Unable to connect to the server. Please check your internet connection and try again.',
        true
      );
    }
    if (payload.currentPassword === 'wrong') {
      throw new ApiError('INVALID_CURRENT_PASSWORD', 'Your current password is incorrect.', false);
    }
    if (payload.newPassword !== payload.confirmNewPassword) {
      throw new ApiError('PASSWORD_MISMATCH', 'The new password and its confirmation do not match.', false);
    }
    const revokedSessions = 1;
    mockAddPasswordChangedNotice(revokedSessions);
    return {
      message: 'Your password has been changed.',
      tokens: {
        accessToken: 'mock_jwt_access_token',
        refreshToken: 'mock_refresh_token',
        tokenType: 'bearer',
        expiresIn: 900,
      },
      revokedSessions,
    };
  }

  async get<T>(endpoint: string): Promise<T> {
    await sleep(config.mockApiLatencyMs);

    // Balances & settlements (T-33): same shapes as the backend, see mockBalances.ts.
    const balances = mockBalancesGet(endpoint);
    if (balances !== undefined) return balances as T;

    // Notification centre (T-36): in-memory demo data, see mockNotifications.ts.
    const notifications = mockNotificationsGet(endpoint);
    if (notifications !== undefined) return notifications as T;

    throw new ApiError(
      'NOT_IMPLEMENTED',
      `Mock GET endpoint "${endpoint}" is not supported.`,
      false
    );
  }

  async post<T>(endpoint: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
    await sleep(config.mockApiLatencyMs);
    const settlement = mockBalancesPost(endpoint, body, headers);
    if (settlement !== undefined) return settlement as T;
    throw new ApiError(
      'NOT_IMPLEMENTED',
      `Mock POST endpoint "${endpoint}" is not supported.`,
      false
    );
  }

  async patch<T>(endpoint: string, _body?: unknown, _headers?: Record<string, string>): Promise<T> {
    await sleep(config.mockApiLatencyMs);
    const notification = mockNotificationsPatch(endpoint);
    if (notification !== undefined) return notification as T;
    throw new ApiError(
      'NOT_IMPLEMENTED',
      `Mock PATCH endpoint "${endpoint}" is not supported.`,
      false
    );
  }

  async put<T>(endpoint: string, body?: unknown, _headers?: Record<string, string>): Promise<T> {
    await sleep(config.mockApiLatencyMs);
    const preferences = mockNotificationsPut(endpoint, body);
    if (preferences !== undefined) return preferences as T;
    throw new ApiError(
      'NOT_IMPLEMENTED',
      `Mock PUT endpoint "${endpoint}" is not supported.`,
      false
    );
  }

  async delete<T>(endpoint: string, _headers?: Record<string, string>): Promise<T> {
    await sleep(config.mockApiLatencyMs);
    throw new ApiError(
      'NOT_IMPLEMENTED',
      `Mock DELETE endpoint "${endpoint}" is not supported.`,
      false
    );
  }
}

export const mockApiClient = new MockApiClient();
