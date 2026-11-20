/**
 * Create-group form validation (T-29 / US-17).
 * Mirrors backend GroupCreateRequest: name 1–100 chars (trimmed, not blank),
 * description up to 500 chars, type one of friends | flat | trip | family.
 */

import { GROUP_TYPES, type CreateGroupInput, type GroupType } from '../types';

export const GROUP_NAME_MAX_LENGTH = 100;
export const GROUP_DESCRIPTION_MAX_LENGTH = 500;

export interface CreateGroupFormValues {
  name: string;
  description: string;
  type: GroupType | null;
}

export type CreateGroupFormErrors = Partial<Record<keyof CreateGroupFormValues, string>>;

export function validateCreateGroup(values: CreateGroupFormValues): CreateGroupFormErrors {
  const errors: CreateGroupFormErrors = {};
  const name = values.name.trim();

  if (name.length === 0) {
    errors.name = 'Enter a group name.';
  } else if (name.length > GROUP_NAME_MAX_LENGTH) {
    errors.name = `Keep the name under ${GROUP_NAME_MAX_LENGTH} characters.`;
  }

  if (values.description.trim().length > GROUP_DESCRIPTION_MAX_LENGTH) {
    errors.description = `Keep the description under ${GROUP_DESCRIPTION_MAX_LENGTH} characters.`;
  }

  if (values.type === null || !GROUP_TYPES.includes(values.type)) {
    errors.type = 'Choose what kind of group this is.';
  }

  return errors;
}

/** Builds the API payload from valid form values. Call only after validation passes. */
export function toCreateGroupInput(values: CreateGroupFormValues): CreateGroupInput {
  const description = values.description.trim();
  return {
    name: values.name.trim(),
    description: description.length > 0 ? description : undefined,
    type: values.type ?? 'friends',
  };
}
