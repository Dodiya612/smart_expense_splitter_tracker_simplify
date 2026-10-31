import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react';
import { registerAuthFailureListener } from '@/services/api/authInterceptor';
import { getApiClient } from '@/services/api/client';
import {
  ApiError,
  AuthResponse,
  AuthUser,
  LoginCredentials,
  SignupPayload,
} from '@/services/api/types';
import { tokenStorage } from '@/services/auth/tokenStorage';

export interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (credentials: LoginCredentials) => Promise<AuthResponse>;
  signup: (payload: SignupPayload) => Promise<AuthResponse>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Restore session on cold start
  useEffect(() => {
    let isMounted = true;

    async function restoreSession() {
      try {
        const [cachedUser, refreshToken] = await Promise.all([
          tokenStorage.getUser(),
          tokenStorage.getRefreshToken(),
        ]);

        if (!refreshToken) {
          if (isMounted) {
            setUser(null);
            setIsLoading(false);
          }
          return;
        }

        // Set cached user optimistically to avoid flash
        if (cachedUser && isMounted) {
          setUser(cachedUser);
        }

        // Validate session with backend /me endpoint
        const client = getApiClient();
        const freshUser = await client.me();
        if (isMounted) {
          setUser(freshUser);
          await tokenStorage.saveUser(freshUser);
        }
      } catch (err: unknown) {
        // Distinguish definitive authentication failure from transient errors
        const isTransient =
          err instanceof ApiError
            ? err.isRetryable
            : err instanceof Error &&
              (err.name === 'AbortError' ||
                err.message.toLowerCase().includes('network') ||
                err.message.toLowerCase().includes('fetch'));

        if (!isTransient) {
          // Definitive auth failure: session is invalid, expired, or revoked
          if (isMounted) {
            setUser(null);
          }
          await tokenStorage.clearAll();
        } else {
          // Transient failure (network drop, timeout, server 5xx):
          // Preserve stored tokens and cached user data so the session survives.
          // Note: If cachedUser was present, setUser(cachedUser) already occurred optimistically.
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    restoreSession();

    // Listen to background refresh token revocation / expiry events
    const unregister = registerAuthFailureListener(() => {
      if (isMounted) {
        setUser(null);
      }
    });

    return () => {
      isMounted = false;
      unregister();
    };
  }, []);

  const login = useCallback(async (credentials: LoginCredentials): Promise<AuthResponse> => {
    const client = getApiClient();
    const response = await client.login(credentials);
    setUser(response.user);
    return response;
  }, []);

  const signup = useCallback(async (payload: SignupPayload): Promise<AuthResponse> => {
    const client = getApiClient();
    const response = await client.signup(payload);
    setUser(response.user);
    return response;
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    try {
      const client = getApiClient();
      await client.logout();
    } finally {
      setUser(null);
      await tokenStorage.clearAll();
    }
  }, []);

  const refreshUser = useCallback(async (): Promise<void> => {
    const client = getApiClient();
    const freshUser = await client.me();
    setUser(freshUser);
    await tokenStorage.saveUser(freshUser);
  }, []);

  const value: AuthContextValue = {
    user,
    isAuthenticated: !!user,
    isLoading,
    login,
    signup,
    logout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
