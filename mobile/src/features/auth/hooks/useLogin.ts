import { useCallback, useRef, useState } from 'react';
import { useAuth } from '@/features/auth/context/AuthContext';
import { LoginFormValues } from '@/features/auth/types';
import { ApiError, AuthUser } from '@/services/api/types';

export function useLogin() {
  const { login: authLogin } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [isSuccess, setIsSuccess] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);

  const lastAttemptRef = useRef<LoginFormValues | null>(null);

  const login = useCallback(async (values: LoginFormValues): Promise<boolean> => {
    lastAttemptRef.current = values;
    setIsLoading(true);
    setError(null);

    try {
      const response = await authLogin({
        email: values.email.trim(),
        password: values.password,
      });

      setUser(response.user);
      setIsSuccess(true);
      return true;

    } catch (err) {
      if (err instanceof ApiError) {
        setError(err);
      } else {
        setError(
          new ApiError(
            'UNKNOWN_ERROR',
            'An unexpected error occurred. Please try again later.',
            true
          )
        );
      }
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [authLogin]);



  const retry = useCallback(async (): Promise<boolean> => {
    if (lastAttemptRef.current) {
      return login(lastAttemptRef.current);
    }
    return false;
  }, [login]);

  const reset = useCallback(() => {
    setIsLoading(false);
    setError(null);
    setIsSuccess(false);
    setUser(null);
    lastAttemptRef.current = null;
  }, []);

  return {
    login,
    retry,
    reset,
    isLoading,
    error,
    isSuccess,
    user,
  };
}
