/**
 * Change-password form rules (T-50). Pure functions, unit tested with `npm test`.
 *
 * These give immediate feedback and block submissions that would certainly fail. The
 * server repeats every check (and verifies the current password); it is the authority.
 */

import type { ApiError } from '@/services/api/types';
import type { AuthFormErrors } from '../types';
import {
  MAX_NEW_PASSWORD_LENGTH,
  MIN_NEW_PASSWORD_LENGTH,
  MIN_PASSWORD_SCORE,
  estimatePasswordStrength,
} from './passwordStrength';

export interface ChangePasswordFormValues {
  currentPassword: string;
  newPassword: string;
  confirmNewPassword: string;
}

export type ChangePasswordErrors = AuthFormErrors<ChangePasswordFormValues>;

export const EMPTY_CHANGE_PASSWORD_VALUES: ChangePasswordFormValues = {
  currentPassword: '',
  newPassword: '',
  confirmNewPassword: '',
};

/** One line per requirement, for the live checklist under the new password field. */
export interface PasswordRequirement {
  key: 'length' | 'strength' | 'match';
  label: string;
  met: boolean;
}

export function passwordRequirements(
  values: ChangePasswordFormValues,
  userInputs: readonly string[] = []
): PasswordRequirement[] {
  const { score } = estimatePasswordStrength(values.newPassword, userInputs);
  return [
    {
      key: 'length',
      label: `At least ${MIN_NEW_PASSWORD_LENGTH} characters`,
      met: values.newPassword.length >= MIN_NEW_PASSWORD_LENGTH,
    },
    {
      key: 'strength',
      label: `Strength at least ${MIN_PASSWORD_SCORE} out of 4`,
      met: values.newPassword.length > 0 && score >= MIN_PASSWORD_SCORE,
    },
    {
      key: 'match',
      label: 'Confirmation matches',
      met: values.confirmNewPassword.length > 0 && values.newPassword === values.confirmNewPassword,
    },
  ];
}

export function validateChangePassword(
  values: ChangePasswordFormValues,
  userInputs: readonly string[] = []
): ChangePasswordErrors {
  const errors: ChangePasswordErrors = {};

  if (!values.currentPassword) {
    errors.currentPassword = 'Enter your current password.';
  }

  if (!values.newPassword) {
    errors.newPassword = 'Enter a new password.';
  } else if (values.newPassword.length < MIN_NEW_PASSWORD_LENGTH) {
    errors.newPassword = `Use at least ${MIN_NEW_PASSWORD_LENGTH} characters.`;
  } else if (values.newPassword.length > MAX_NEW_PASSWORD_LENGTH) {
    errors.newPassword = `Use at most ${MAX_NEW_PASSWORD_LENGTH} characters.`;
  } else {
    const strength = estimatePasswordStrength(values.newPassword, userInputs);
    if (strength.score < MIN_PASSWORD_SCORE) {
      errors.newPassword = `Too weak (${strength.score}/4). ${strength.feedback[0] ?? 'Choose a stronger password.'}`;
    } else if (values.currentPassword && values.newPassword === values.currentPassword) {
      errors.newPassword = 'Choose a password different from your current one.';
    }
  }

  if (!values.confirmNewPassword) {
    errors.confirmNewPassword = 'Confirm your new password.';
  } else if (values.newPassword !== values.confirmNewPassword) {
    errors.confirmNewPassword = 'Passwords do not match.';
  }

  return errors;
}

export function canSubmitChangePassword(
  values: ChangePasswordFormValues,
  userInputs: readonly string[] = []
): boolean {
  return Object.keys(validateChangePassword(values, userInputs)).length === 0;
}

/**
 * Maps a server error to field errors or a banner. Field errors are for problems the
 * user fixes in a field; everything else (network, rate limit, session) is a banner.
 */
export function mapChangePasswordError(error: ApiError): {
  fieldErrors: ChangePasswordErrors;
  banner: string | null;
} {
  switch (error.code) {
    case 'INVALID_CURRENT_PASSWORD':
      return { fieldErrors: { currentPassword: 'Your current password is incorrect.' }, banner: null };
    case 'PASSWORD_TOO_SHORT':
    case 'WEAK_PASSWORD':
    case 'PASSWORD_UNCHANGED': {
      const hint = error.detail?.find((d) => typeof d.msg === 'string')?.msg;
      return { fieldErrors: { newPassword: hint ? `${error.message} ${hint}` : error.message }, banner: null };
    }
    case 'PASSWORD_MISMATCH':
      return { fieldErrors: { confirmNewPassword: 'Passwords do not match.' }, banner: null };
    default:
      return { fieldErrors: {}, banner: error.message || 'Could not change your password. Please try again.' };
  }
}

/** Confirmation text shown in the app right after a successful change. */
export function successMessage(revokedSessions: number): string {
  if (revokedSessions <= 0) return 'Your password has been changed. You are still signed in on this device.';
  const devices = revokedSessions === 1 ? 'device' : 'devices';
  return `Your password has been changed. You were signed out on ${revokedSessions} other ${devices}; this device stays signed in.`;
}
