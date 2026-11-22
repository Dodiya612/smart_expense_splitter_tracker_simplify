/**
 * Join-by-code form state and submission (T-29 / US-17).
 * Accepts a bare code or a pasted invite link.
 */

import { useCallback, useState } from 'react';
import { joinGroupByCode } from '../services/groupsApi';
import type { GroupDetail } from '../types';
import { extractJoinCode, joinErrorMessage, validateJoinCode } from '../utils/joinCode';
import { toApiError } from './useGroups';

export interface UseJoinGroupReturn {
  input: string;
  fieldError?: string;
  submitError: string | null;
  submitErrorCode: string | null;
  isSubmitting: boolean;
  setInput: (text: string) => void;
  submit: () => Promise<GroupDetail | null>;
}

export function useJoinGroup(initialCode = ''): UseJoinGroupReturn {
  const [input, setInputState] = useState(initialCode);
  const [fieldError, setFieldError] = useState<string | undefined>(undefined);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitErrorCode, setSubmitErrorCode] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const setInput = useCallback((text: string) => {
    setInputState(text);
    setFieldError(undefined);
    setSubmitError(null);
    setSubmitErrorCode(null);
  }, []);

  const submit = useCallback(async (): Promise<GroupDetail | null> => {
    if (isSubmitting) return null;
    const code = extractJoinCode(input);
    const error = validateJoinCode(code);
    if (error) {
      setFieldError(error);
      return null;
    }
    setIsSubmitting(true);
    setSubmitError(null);
    setSubmitErrorCode(null);
    try {
      return await joinGroupByCode(code);
    } catch (err) {
      const apiError = toApiError(err, 'JOIN_FAILED', 'Could not join the group. Please try again.');
      setSubmitErrorCode(apiError.code);
      setSubmitError(joinErrorMessage(apiError.code, apiError.message));
      return null;
    } finally {
      setIsSubmitting(false);
    }
  }, [input, isSubmitting]);

  return { input, fieldError, submitError, submitErrorCode, isSubmitting, setInput, submit };
}
