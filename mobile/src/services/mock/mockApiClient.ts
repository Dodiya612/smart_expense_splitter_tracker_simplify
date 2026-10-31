import { config } from '@/constants/config';
import {
  ApiClient,
  ApiError,
  AuthResponse,
  LoginCredentials,
  SignupPayload,
} from '@/services/api/types';

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Deterministic mock implementation of the ApiClient.
 *
 * Deterministic triggers for testing:
 * - Email containing "network.error" simulates a retryable network drop.
 * - Email containing "invalid" simulates bad credentials (non-retryable).
 * - Email containing "exists" simulates an existing account collision during sign-up.
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
}

export const mockApiClient = new MockApiClient();
