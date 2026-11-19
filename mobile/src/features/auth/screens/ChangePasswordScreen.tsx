/**
 * Change password (T-50): current password, new password with real-time strength
 * feedback, and confirmation. On success the server signs out every other device and
 * this device stays signed in with the new tokens.
 */

import React, { useMemo, useRef, useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';
import { Href, router } from 'expo-router';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { AuthErrorBanner } from '@/features/auth/components/AuthErrorBanner';
import { ChangePasswordSuccess } from '@/features/auth/components/ChangePasswordSuccess';
import { PasswordStrengthMeter } from '@/features/auth/components/PasswordStrengthMeter';
import { useAuth } from '@/features/auth/context/AuthContext';
import { useChangePassword } from '@/features/auth/hooks/useChangePassword';
import {
  ChangePasswordErrors,
  ChangePasswordFormValues,
  EMPTY_CHANGE_PASSWORD_VALUES,
  canSubmitChangePassword,
  mapChangePasswordError,
  passwordRequirements,
  successMessage,
} from '@/features/auth/utils/changePassword';
import { estimatePasswordStrength } from '@/features/auth/utils/passwordStrength';
import { GroupScreenHeader } from '@/features/groups/components/GroupScreenHeader';
import { useTheme } from '@/theme';

export function ChangePasswordScreen() {
  const theme = useTheme();
  const { user } = useAuth();
  const { changePassword, clearError, isLoading, success } = useChangePassword();
  const newRef = useRef<TextInput>(null);
  const confirmRef = useRef<TextInput>(null);
  const [values, setValues] = useState<ChangePasswordFormValues>(EMPTY_CHANGE_PASSWORD_VALUES);
  const [fieldErrors, setFieldErrors] = useState<ChangePasswordErrors>({});
  const [banner, setBanner] = useState<{ message: string; retryable: boolean } | null>(null);

  const userInputs = useMemo(() => [user?.name ?? '', user?.email ?? ''], [user]);
  const strength = estimatePasswordStrength(values.newPassword, userInputs);
  const requirements = passwordRequirements(values, userInputs);
  const canSubmit = canSubmitChangePassword(values, userInputs) && !isLoading;
  const mismatch = values.confirmNewPassword.length > 0 && values.confirmNewPassword !== values.newPassword;

  const handleChange = (field: keyof ChangePasswordFormValues, text: string) => {
    setValues((prev) => ({ ...prev, [field]: text }));
    setFieldErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));
    setBanner(null);
    clearError();
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const error = await changePassword(values);
    if (!error) {
      setValues(EMPTY_CHANGE_PASSWORD_VALUES); // do not keep passwords in memory
      return;
    }
    const mapped = mapChangePasswordError(error);
    setFieldErrors(mapped.fieldErrors);
    setBanner(mapped.banner ? { message: mapped.banner, retryable: error.isRetryable } : null);
  };

  if (success) {
    return (
      <ScreenContainer scrollable>
        <GroupScreenHeader title="Change password" />
        <ChangePasswordSuccess
          message={successMessage(success.revokedSessions)}
          onDone={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)/home' as Href))}
          onViewNotifications={() => router.replace('/notifications' as Href)}
        />
      </ScreenContainer>
    );
  }

  const common = { secureTextEntry: true, autoCapitalize: 'none', autoCorrect: false, disabled: isLoading } as const;

  return (
    <ScreenContainer scrollable>
      <GroupScreenHeader title="Change password" subtitle="This signs you out on your other devices" />
      <View style={[styles.form, { gap: theme.spacing.md }]}>
        {banner ? (
          <AuthErrorBanner message={banner.message} isRetryable={banner.retryable} onRetry={handleSubmit} />
        ) : null}
        <AppInput
          {...common}
          label="Current password"
          value={values.currentPassword}
          onChangeText={(t) => handleChange('currentPassword', t)}
          autoComplete="current-password"
          textContentType="password"
          returnKeyType="next"
          onSubmitEditing={() => newRef.current?.focus()}
          error={fieldErrors.currentPassword}
        />
        <AppInput
          {...common}
          ref={newRef}
          label="New password"
          value={values.newPassword}
          onChangeText={(t) => handleChange('newPassword', t)}
          placeholder="At least 10 characters"
          autoComplete="new-password"
          textContentType="newPassword"
          returnKeyType="next"
          onSubmitEditing={() => confirmRef.current?.focus()}
          error={fieldErrors.newPassword}
        />
        <PasswordStrengthMeter strength={strength} requirements={requirements} />
        <AppInput
          {...common}
          ref={confirmRef}
          label="Confirm new password"
          value={values.confirmNewPassword}
          onChangeText={(t) => handleChange('confirmNewPassword', t)}
          autoComplete="new-password"
          textContentType="newPassword"
          returnKeyType="done"
          onSubmitEditing={handleSubmit}
          error={fieldErrors.confirmNewPassword ?? (mismatch ? 'Passwords do not match.' : undefined)}
        />
        <Button
          label="Change password"
          fullWidth
          loading={isLoading}
          disabled={!canSubmit}
          accessibilityHint={canSubmit ? undefined : 'Complete every requirement above to continue'}
          onPress={handleSubmit}
        />
        <AppText variant="caption" color="textSecondary">
          Other phones and computers signed in to your account will need to log in again with the new
          password.
        </AppText>
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  form: { width: '100%' },
});
