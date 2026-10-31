export interface RuntimeEnvironment {
  platformOs?: string;
  hostUri?: string | null;
  isDev?: boolean;
}

let runtimeEnv: RuntimeEnvironment = {
  platformOs: 'unknown',
  hostUri: null,
  isDev: false,
};

export function configureApiRuntime(env: RuntimeEnvironment): void {
  runtimeEnv = { ...runtimeEnv, ...env };
}

export function getRuntimeEnvironment(): RuntimeEnvironment {
  return runtimeEnv;
}

/**
 * Resolves the backend API base URL adaptively:
 * 1. Explicit override from EXPO_PUBLIC_API_URL if present.
 * 2. In __DEV__, derive host from Constants.expoConfig?.hostUri (Metro server IP:8000),
 *    which enables physical devices connected over LAN / Expo Go to reach the backend.
 * 3. Platform fallback:
 *    - Android emulator: 'http://10.0.2.2:8000' (loopback alias to host machine)
 *    - iOS Simulator / Web / default: 'http://localhost:8000'
 */
export function resolveApiBaseUrl(envOverride?: string): string {
  // 1. Explicit environment variable override
  const envUrl = envOverride || process.env.EXPO_PUBLIC_API_URL;
  if (envUrl && envUrl.trim().length > 0) {
    return envUrl.trim().replace(/\/+$/, '');
  }

  // 2. Metro dev server host derivation
  if (runtimeEnv.isDev && runtimeEnv.hostUri) {
    const ip = runtimeEnv.hostUri.split(':')[0];
    if (ip && ip !== 'localhost' && ip !== '127.0.0.1') {
      return `http://${ip}:8000`;
    }
  }

  // 3. Platform-specific fallbacks
  if (runtimeEnv.platformOs === 'android') {
    return 'http://10.0.2.2:8000';
  }

  return 'http://localhost:8000';
}

export const API_TIMEOUT_MS = 15000;
