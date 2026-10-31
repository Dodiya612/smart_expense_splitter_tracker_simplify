import Constants from 'expo-constants';
import { Platform } from 'react-native';
import {
  API_TIMEOUT_MS,
  configureApiRuntime,
  resolveApiBaseUrl,
} from './apiConfig';

// Initialize the API runtime environment with native platform details
configureApiRuntime({
  platformOs: Platform.OS,
  hostUri: Constants.expoConfig?.hostUri,
  isDev: typeof __DEV__ !== 'undefined' ? __DEV__ : false,
});

/**
 * App-wide configuration (non-theme).
 */
export const config = {
  /** API Base URL pointing to the FastAPI backend. */
  get apiUrl(): string {
    return resolveApiBaseUrl();
  },

  /**
   * When true, ApiClient points to the mock implementation instead of FastAPI.
   * Can be toggled via EXPO_PUBLIC_USE_MOCK_API environment variable or manually.
   */
  useMockApi: process.env.EXPO_PUBLIC_USE_MOCK_API === 'true',

  /** Simulated network latency in milliseconds for deterministic mock testing. */
  mockApiLatencyMs: 400,

  /** Request timeout in milliseconds. */
  requestTimeoutMs: API_TIMEOUT_MS,
};

export { resolveApiBaseUrl };
