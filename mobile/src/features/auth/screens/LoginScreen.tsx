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
import { useLogin } from '@/features/auth/hooks/useLogin';
import { AuthFormErrors, LoginFormValues } from '@/features/auth/types';
import { validateLogin } from '@/features/auth/utils/validation';
import { useTheme } from '@/theme';

export function LoginScreen() {
  const theme = useTheme();
  const passwordRef = useRef<TextInput>(null);
  const { login, retry, isLoading, error } = useLogin();
  const {
    scrollViewRef,
    topPadding,
    onScroll,
    onScrollViewLayout,
    onFormContentLayout,
    onFormLayout,
    onContainerLayout,
    ensureFieldVisible,
  } = useKeyboardAwareScroll();

  const [values, setValues] = useState<LoginFormValues>({ email: '', password: '' });
  const [fieldErrors, setFieldErrors] = useState<AuthFormErrors<LoginFormValues>>({});

  const handleFieldChange = (field: keyof LoginFormValues, text: string) => {
    setValues((prev) => ({ ...prev, [field]: text }));
    if (fieldErrors[field]) setFieldErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const handleSubmit = async () => {
    const errors = validateLogin(values);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      const firstError = Object.keys(errors)[0];
      if (firstError) ensureFieldVisible(firstError);
      return;
    }
    setFieldErrors({});
    const success = await login(values);
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
    <ScreenContainer
      scrollable
      scrollViewRef={scrollViewRef}
      onScroll={onScroll}
      onScrollViewLayout={onScrollViewLayout}
      contentContainerStyle={{ paddingTop: topPadding }}>
      <View onLayout={onFormContentLayout} style={[styles.contentWrapper, { gap: theme.spacing.xl }]}>
        <AuthHeader title="Welcome back" subtitle="Log in to track and split shared expenses" />
        <View onLayout={onFormLayout} style={[styles.form, { gap: theme.spacing.md }]}>
          {error && <AuthErrorBanner message={error.message} isRetryable={error.isRetryable} onRetry={handleRetry} />}
          <AppInput
            label="Email address"
            value={values.email}
            onChangeText={(text) => handleFieldChange('email', text)}
            onContainerLayout={onContainerLayout('email')}
            onFocus={() => ensureFieldVisible('email')}
            placeholder="name@example.in"
            keyboardType="email-address"
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="email"
            textContentType="emailAddress"
            returnKeyType="next"
            onSubmitEditing={() => { passwordRef.current?.focus(); ensureFieldVisible('password'); }}
            error={fieldErrors.email}
            disabled={isLoading}
          />
          <AppInput
            ref={passwordRef}
            label="Password"
            value={values.password}
            onChangeText={(text) => handleFieldChange('password', text)}
            onContainerLayout={onContainerLayout('password')}
            onFocus={() => ensureFieldVisible('password')}
            placeholder="Enter your password"
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="current-password"
            textContentType="password"
            returnKeyType="done"
            onSubmitEditing={handleSubmit}
            error={fieldErrors.password}
            disabled={isLoading}
          />
          <Button label="Log in" variant="primary" fullWidth loading={isLoading} disabled={isLoading} onPress={handleSubmit} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Don't have an account? Sign up"
            disabled={isLoading}
            onPress={() => router.push('/signup' as Href)}
            style={({ pressed }) => [styles.navLink, { minHeight: theme.minTouchTarget }, pressed && styles.pressed]}>
            <AppText variant="small" color="textSecondary">
              {"Don't have an account? "}
              <AppText variant="small" color="textPrimary" style={styles.boldText}>Sign up</AppText>
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
  navLink: { alignItems: 'center', justifyContent: 'center', paddingVertical: 8 },
  boldText: { fontWeight: '600' },
  pressed: { opacity: 0.7 },
});
