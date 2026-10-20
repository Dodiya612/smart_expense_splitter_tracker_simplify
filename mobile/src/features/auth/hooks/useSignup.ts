import { useCallback, useRef, useState } from 'react';
import { useAuth } from '@/features/auth/context/AuthContext';
import { SignupFormValues } from '@/features/auth/types';
import { ApiError, AuthUser } from '@/services/api/types';

export function useSignup() {
  const { signup: authSignup } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [isSuccess, setIsSuccess] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);

  const lastAttemptRef = useRef<SignupFormValues | null>(null);

  const signup = useCallback(async (values: SignupFormValues): Promise<boolean> => {
    lastAttemptRef.current = values;
    setIsLoading(true);
    setError(null);

    try {
      const response = await authSignup({
        name: values.name.trim(),
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
  }, [authSignup]);



  const retry = useCallback(async (): Promise<boolean> => {
    if (lastAttemptRef.current) {
      return signup(lastAttemptRef.current);
    }
    return false;
  }, [signup]);

  const reset = useCallback(() => {
    setIsLoading(false);
    setError(null);
    setIsSuccess(false);
    setUser(null);
    lastAttemptRef.current = null;
  }, []);

  return {
    signup,
    retry,
    reset,
    isLoading,
    error,
    isSuccess,
    user,
  };
}
