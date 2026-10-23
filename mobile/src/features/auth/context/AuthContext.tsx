import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { ApiError, AuthUser } from '@/services/api/types';
import {
  clearStoredAuthSession,
  getStoredAuthSession,
  setStoredAuthSession,
} from '@/services/auth/secureStoreAdapter';

interface AuthCredentials {
  email: string;
  password: string;
}

interface SignupPayload extends AuthCredentials {
  name: string;
}

interface AuthResponse {
  user: AuthUser;
}

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: AuthUser | null;
  login: (payload: AuthCredentials) => Promise<AuthResponse>;
  signup: (payload: SignupPayload) => Promise<AuthResponse>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function createMockUser(name: string, email: string): AuthUser {
  return {
    id: email.trim().toLowerCase(),
    name: name.trim() || email.split('@')[0] || 'User',
    email: email.trim(),
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    const hydrateAuth = async () => {
      try {
        const session = await getStoredAuthSession();
        if (isMounted && session) {
          setUser({
            id: session.userId,
            name: 'User',
            email: session.userId,
          });
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    hydrateAuth();

    return () => {
      isMounted = false;
    };
  }, []);

  const login = useCallback(async ({ email, password }: AuthCredentials): Promise<AuthResponse> => {
    if (!email.trim() || !password) {
      throw new ApiError('INVALID_CREDENTIALS', 'Email and password are required.');
    }

    const nextUser = createMockUser('', email);
    setUser(nextUser);
    await setStoredAuthSession({ userId: nextUser.id });
    return { user: nextUser };
  }, []);

  const signup = useCallback(async ({ name, email, password }: SignupPayload): Promise<AuthResponse> => {
    if (!name.trim() || !email.trim() || !password) {
      throw new ApiError('INVALID_INPUT', 'Name, email, and password are required.');
    }

    const nextUser = createMockUser(name, email);
    setUser(nextUser);
    await setStoredAuthSession({ userId: nextUser.id });
    return { user: nextUser };
  }, []);

  const logout = useCallback(async () => {
    setUser(null);
    await clearStoredAuthSession();
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    isAuthenticated: Boolean(user),
    isLoading,
    user,
    login,
    signup,
    logout,
  }), [isLoading, login, logout, signup, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
