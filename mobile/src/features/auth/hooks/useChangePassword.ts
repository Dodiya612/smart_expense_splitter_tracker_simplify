import { useCallback, useRef, useState } from 'react';
import { getApiClient } from '@/services/api/client';
import { ApiError } from '@/services/api/types';
import { ChangePasswordFormValues } from '../utils/changePassword';

export interface ChangePasswordSuccess {
  message: string;
  revokedSessions: number;
}

/**
 * Submits a password change (T-50). Passwords live only in the form state and the single
 * request body; they are never stored, logged or kept here after the request.
 */
export function useChangePassword() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState<ChangePasswordSuccess | null>(null);
  const inFlight = useRef(false);

  /** Resolves to null on success, or the error (also kept in `error`). */
  const changePassword = useCallback(async (values: ChangePasswordFormValues): Promise<ApiError | null> => {
    if (inFlight.current) return null; // no double submit; the running request reports
    inFlight.current = true;
    setIsLoading(true);
    setError(null);
    try {
      const response = await getApiClient().changePassword({
        currentPassword: values.currentPassword,
        newPassword: values.newPassword,
        confirmNewPassword: values.confirmNewPassword,
      });
      setSuccess({ message: response.message, revokedSessions: response.revokedSessions ?? 0 });
      return null;
    } catch (err) {
      const apiError =
        err instanceof ApiError
          ? err
          : new ApiError('UNKNOWN_ERROR', 'Something went wrong. Please try again.', true);
      setError(apiError);
      return apiError;
    } finally {
      inFlight.current = false;
      setIsLoading(false);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { changePassword, clearError, isLoading, error, success };
}
