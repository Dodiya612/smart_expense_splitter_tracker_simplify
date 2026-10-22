import type { AuthFormErrors, LoginFormValues, SignupFormValues } from '../types';

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LENGTH = 8;

export function isValidEmail(email: string): boolean {
  return EMAIL_REGEX.test(email.trim());
}

export function validateLogin(values: LoginFormValues): AuthFormErrors<LoginFormValues> {
  const errors: AuthFormErrors<LoginFormValues> = {};

  const trimmedEmail = values.email.trim();
  if (!trimmedEmail) {
    errors.email = 'Email address is required.';
  } else if (!isValidEmail(trimmedEmail)) {
    errors.email = 'Enter a valid email address.';
  }

  if (!values.password) {
    errors.password = 'Password is required.';
  }

  return errors;
}

export function validateSignup(values: SignupFormValues): AuthFormErrors<SignupFormValues> {
  const errors: AuthFormErrors<SignupFormValues> = {};

  const trimmedName = values.name.trim();
  if (!trimmedName) {
    errors.name = 'Full name is required.';
  }

  const trimmedEmail = values.email.trim();
  if (!trimmedEmail) {
    errors.email = 'Email address is required.';
  } else if (!isValidEmail(trimmedEmail)) {
    errors.email = 'Enter a valid email address.';
  }

  if (!values.password) {
    errors.password = 'Password is required.';
  } else if (values.password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }

  if (!values.confirmPassword) {
    errors.confirmPassword = 'Confirm your password.';
  } else if (values.password !== values.confirmPassword) {
    errors.confirmPassword = 'Passwords do not match.';
  }

  return errors;
}
