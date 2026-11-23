/**
 * Create-group form state and submission (T-29 / US-17).
 * On success the one-time join code is remembered so the group screen can share it.
 */

import { useCallback, useState } from 'react';
import { ApiError } from '@/services/api/types';
import { createGroup } from '../services/groupsApi';
import type { GroupDetail, GroupType } from '../types';
import { rememberJoinCode } from '../utils/joinCodeCache';
import {
  toCreateGroupInput,
  validateCreateGroup,
  type CreateGroupFormErrors,
  type CreateGroupFormValues,
} from '../utils/validation';
import { toApiError } from './useGroups';

export interface UseCreateGroupReturn {
  values: CreateGroupFormValues;
  fieldErrors: CreateGroupFormErrors;
  submitError: ApiError | null;
  isSubmitting: boolean;
  setName: (text: string) => void;
  setDescription: (text: string) => void;
  setType: (type: GroupType) => void;
  submit: () => Promise<GroupDetail | null>;
}

export function useCreateGroup(): UseCreateGroupReturn {
  const [values, setValues] = useState<CreateGroupFormValues>({
    name: '',
    description: '',
    type: null,
  });
  const [fieldErrors, setFieldErrors] = useState<CreateGroupFormErrors>({});
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const update = useCallback(
    <K extends keyof CreateGroupFormValues>(field: K, value: CreateGroupFormValues[K]) => {
      setValues((prev) => ({ ...prev, [field]: value }));
      setFieldErrors((prev) => ({ ...prev, [field]: undefined }));
      setSubmitError(null);
    },
    []
  );

  const submit = useCallback(async (): Promise<GroupDetail | null> => {
    if (isSubmitting) return null;
    const errors = validateCreateGroup(values);
    if (Object.values(errors).some(Boolean)) {
      setFieldErrors(errors);
      return null;
    }
    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const group = await createGroup(toCreateGroupInput(values));
      if (group.joinCode) {
        rememberJoinCode({ groupId: group.id, code: group.joinCode, expiresAt: '' });
      }
      return group;
    } catch (err) {
      setSubmitError(
        toApiError(err, 'GROUP_CREATE_FAILED', 'Could not create the group. Please try again.')
      );
      return null;
    } finally {
      setIsSubmitting(false);
    }
  }, [isSubmitting, values]);

  return {
    values,
    fieldErrors,
    submitError,
    isSubmitting,
    setName: (text) => update('name', text),
    setDescription: (text) => update('description', text),
    setType: (type) => update('type', type),
    submit,
  };
}
