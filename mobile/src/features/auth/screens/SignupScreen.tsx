import React, { useRef, useState } from 'react';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';
import { Href, router } from 'expo-router';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { AuthErrorBanner } from '@/features/auth/components/AuthErrorBanner';
import { AuthHeader } from '@/features/auth/components/AuthHeader';
import { useKeyboardAwareScroll } from '@/features/auth/hooks/useKeyboardAwareScroll';
import { useSignup } from '@/features/auth/hooks/useSignup';
import { AuthFormErrors, SignupFormValues } from '@/features/auth/types';
import { getPasswordStrength, validateSignup } from '@/features/auth/utils/validation';
import { useTheme } from '@/theme';

const INITIAL_VALUES: SignupFormValues = { name: '', email: '', password: '', confirmPassword: '' };

export function SignupScreen() {
  const theme = useTheme();
  const emailRef = useRef<TextInput>(null);
  const passwordRef = useRef<TextInput>(null);
  const confirmPasswordRef = useRef<TextInput>(null);
  const { signup, retry, isLoading, error } = useSignup();
  const {
    scrollViewRef, topPadding, onScroll, onScrollViewLayout,
    onFormContentLayout, onFormLayout, onContainerLayout, ensureFieldVisible,
  } = useKeyboardAwareScroll();
  const [values, setValues] = useState<SignupFormValues>(INITIAL_VALUES);
  const [fieldErrors, setFieldErrors] = useState<AuthFormErrors<SignupFormValues>>({});

  const passwordStrength = getPasswordStrength(values.password);

  const handleFieldChange = (field: keyof SignupFormValues, text: string) => {
    setValues((prev) => ({ ...prev, [field]: text }));
    setFieldErrors((prev) => {
      if (!prev[field] && !(field === 'password' && prev.confirmPassword)) {
        return prev;
      }
      const updated = { ...prev, [field]: undefined };
      if (field === 'password') {
        updated.confirmPassword = undefined;
      }
      return updated;
    });
  };

  const handleSubmit = async () => {
    const errors = validateSignup(values);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      const firstError = Object.keys(errors)[0];
      if (firstError) ensureFieldVisible(firstError);
      return;
    }
    setFieldErrors({});
    const success = await signup(values);
    if (success) {
      router.replace('/(tabs)/home' as Href);
    }
  };

  const handleRetry = async () => {
    const success = await retry();
    if (success) {
      router.replace('/(tabs)/home' as Href);
    }
  };

  return (
    <ScreenContainer scrollable scrollViewRef={scrollViewRef} onScroll={onScroll} onScrollViewLayout={onScrollViewLayout} contentContainerStyle={{ paddingTop: topPadding }}>
      <View onLayout={onFormContentLayout} style={[styles.contentWrapper, { gap: theme.spacing.xl }]}>
        <AuthHeader title="Create account" subtitle="Join to split bills and track expenses in INR" />
        <View onLayout={onFormLayout} style={[styles.form, { gap: theme.spacing.md }]}>
          {error && (
            <AuthErrorBanner
              message={error.message}
              isRetryable={error.isRetryable}
              onRetry={handleRetry}
              actionLabel={error.code === 'EMAIL_ALREADY_EXISTS' ? 'Log in instead' : undefined}
              onAction={
                error.code === 'EMAIL_ALREADY_EXISTS'
                  ? () => router.replace('/login' as Href)
                  : undefined
              }
            />
          )}
            <AppInput
              label="Full name" value={values.name}
              onChangeText={(text) => handleFieldChange('name', text)}
              onContainerLayout={onContainerLayout('name')}
              onFocus={() => ensureFieldVisible('name')}
              placeholder="e.g. Priya Patel" autoCapitalize="words"
              autoCorrect={false} autoComplete="name" textContentType="name"
              returnKeyType="next"
              onSubmitEditing={() => { emailRef.current?.focus(); ensureFieldVisible('email'); }}
              error={fieldErrors.name} disabled={isLoading}
            />
            <AppInput
              ref={emailRef} label="Email address" value={values.email}
              onChangeText={(text) => handleFieldChange('email', text)}
              onContainerLayout={onContainerLayout('email')}
              onFocus={() => ensureFieldVisible('email')}
              placeholder="name@example.in" keyboardType="email-address"
              autoCapitalize="none" autoCorrect={false} autoComplete="email"
              textContentType="emailAddress" returnKeyType="next"
              onSubmitEditing={() => { passwordRef.current?.focus(); ensureFieldVisible('password'); }}
              error={fieldErrors.email} disabled={isLoading}
            />
            <AppInput
              ref={passwordRef} label="Password" value={values.password}
              onChangeText={(text) => handleFieldChange('password', text)}
              onContainerLayout={onContainerLayout('password')}
              onFocus={() => ensureFieldVisible('password')}
              placeholder="At least 8 characters"
              helperText={values.password.length === 0 ? 'Must be at least 8 characters' : undefined}
              secureTextEntry autoCapitalize="none" autoCorrect={false}
              autoComplete="new-password" textContentType="newPassword"
              returnKeyType="next"
              onSubmitEditing={() => { confirmPasswordRef.current?.focus(); ensureFieldVisible('confirmPassword'); }}
              error={fieldErrors.password} disabled={isLoading}
            />
            {passwordStrength && (
              <View
                style={styles.strengthContainer}
                accessibilityRole="progressbar"
                accessibilityLabel={`Password strength: ${passwordStrength.label}`}>
                <View style={styles.strengthBars}>
                  {[1, 2, 3].map((barIndex) => {
                    const isActive = barIndex <= passwordStrength.score;
                    let barColor: string = theme.colors.border;
                    if (isActive) {
                      if (passwordStrength.level === 'weak') barColor = theme.colors.negative.fill;
                      else if (passwordStrength.level === 'fair') barColor = theme.colors.warning.fill;
                      else barColor = theme.colors.positive.fill;
                    }
                    return (
                      <View key={barIndex} style={[styles.strengthBar, { backgroundColor: barColor }]} />
                    );
                  })}
                </View>
                <AppText
                  variant="caption"
                  color={
                    passwordStrength.level === 'weak'
                      ? 'negative'
                      : passwordStrength.level === 'fair'
                      ? 'warning'
                      : 'positive'
                  }>
                  {`Strength: ${passwordStrength.label}`}
                </AppText>
              </View>
            )}
            <AppInput
              ref={confirmPasswordRef} label="Confirm password" value={values.confirmPassword}
              onChangeText={(text) => handleFieldChange('confirmPassword', text)}
              onContainerLayout={onContainerLayout('confirmPassword')}
              onFocus={() => ensureFieldVisible('confirmPassword')}
              placeholder="Re-enter your password" secureTextEntry
              autoCapitalize="none" autoCorrect={false}
              autoComplete="new-password" textContentType="newPassword"
              returnKeyType="done" onSubmitEditing={handleSubmit}
              error={fieldErrors.confirmPassword} disabled={isLoading}
            />
            {values.confirmPassword.length > 0 && !fieldErrors.confirmPassword && (
              <View style={styles.confirmFeedback}>
                {values.password === values.confirmPassword ? (
                  <AppText variant="caption" color="positive" accessibilityLiveRegion="polite">
                    ✓ Passwords match
                  </AppText>
                ) : (
                  <AppText variant="caption" color="negative" accessibilityLiveRegion="polite">
                    [!] Passwords do not match
                  </AppText>
                )}
              </View>
            )}
            <Button label="Create account" variant="primary" fullWidth loading={isLoading} disabled={isLoading} onPress={handleSubmit} />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Already have an account? Log in"
              accessibilityHint="Navigates to the log in screen"
              disabled={isLoading}
              onPress={() => router.replace('/login' as Href)}
              style={({ pressed }) => [styles.navLink, { minHeight: theme.minTouchTarget }, pressed && styles.pressed]}>
              <AppText variant="small" color="textSecondary">
                Already have an account?{' '}
                <AppText variant="small" color="textPrimary" style={styles.boldText}>
                  Log in
                </AppText>
              </AppText>
            </Pressable>
          </View>
        </View>
      </ScreenContainer>
    );
  }

  const styles = StyleSheet.create({
    contentWrapper: { width: '100%' },
    form: { width: '100%' },
    strengthContainer: { gap: 4, marginTop: -4 },
    strengthBars: { flexDirection: 'row', gap: 4, width: '100%' },
    strengthBar: { flex: 1, height: 4, borderRadius: 2 },
    confirmFeedback: { marginTop: -4 },
    navLink: { alignItems: 'center', justifyContent: 'center', paddingVertical: 8 },
    boldText: { fontFamily: 'Inter_600SemiBold', fontWeight: '600' },
    pressed: { opacity: 0.7 },
  });
