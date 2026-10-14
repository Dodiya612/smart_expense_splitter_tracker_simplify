import React, { useId, useState } from 'react';
import {
  Platform,
  Pressable,
  StyleProp,
  StyleSheet,
  TextInput,
  TextInputProps,
  TextStyle,
  View,
  ViewStyle,
} from 'react-native';
import { useTheme } from '@/theme';
import { AppText } from './AppText';

export interface AppInputProps extends Omit<TextInputProps, 'style' | 'editable'> {
  label: string;
  error?: string;
  helperText?: string;
  disabled?: boolean;
  containerStyle?: StyleProp<ViewStyle>;
  inputStyle?: StyleProp<TextStyle>;
}

export type AppInputRef = TextInput;

export const AppInput = React.forwardRef<TextInput, AppInputProps>(function AppInput(
  {
    label,
    error,
    helperText,
    disabled = false,
    containerStyle,
    inputStyle,
    secureTextEntry = false,
    onFocus,
    onBlur,
    accessibilityLabel,
    accessibilityHint,
    ...restProps
  },
  ref
) {
  const theme = useTheme();
  const id = useId().replace(/:/g, '_');
  const labelId = `${id}-l`;
  const errorId = `${id}-e`;

  const [isFocused, setIsFocused] = useState(false);
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const isSecure = secureTextEntry && !isPasswordVisible;

  let borderColor: string = theme.colors.borderStrong;
  let borderWidth = 1;
  if (error) {
    borderColor = theme.colors.negative.text;
    borderWidth = 1.5;
  } else if (isFocused) {
    borderColor = theme.colors.primary;
    borderWidth = 1.5;
  }

  const iosLabel = error ? `${label}, error: ${error}` : label;
  const a11yLabel = accessibilityLabel ?? (Platform.OS === 'ios' ? iosLabel : label);
  const a11yHint = accessibilityHint ?? (error ? `Error: ${error}` : helperText);

  return (
    <View style={[styles.container, containerStyle]}>
      <AppText variant="small" color={disabled ? 'textSecondary' : 'textPrimary'} nativeID={labelId}>
        {label}
      </AppText>
      <View
        style={[
          styles.wrapper,
          {
            backgroundColor: disabled ? theme.colors.surfaceMuted : theme.colors.surface,
            borderColor,
            borderWidth,
            borderRadius: theme.radii.md,
            minHeight: theme.minTouchTarget,
            paddingHorizontal: theme.spacing.md,
          },
        ]}>
        <TextInput
          ref={ref}
          editable={!disabled}
          secureTextEntry={isSecure}
          placeholderTextColor={theme.colors.textSecondary}
          accessibilityLabel={a11yLabel}
          accessibilityHint={a11yHint}
          accessibilityState={{ disabled }}
          {...(Platform.OS === 'android' ? { accessibilityLabelledBy: error ? [labelId, errorId] : labelId } : {})}
          onFocus={(e) => { setIsFocused(true); onFocus?.(e); }}
          onBlur={(e) => { setIsFocused(false); onBlur?.(e); }}
          style={[theme.typography.body, styles.input, { color: disabled ? theme.colors.textSecondary : theme.colors.textPrimary }, inputStyle]}
          {...restProps}
        />
        {secureTextEntry && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={isPasswordVisible ? 'Hide password' : 'Show password'}
            disabled={disabled}
            onPress={() => setIsPasswordVisible((v) => !v)}
            style={({ pressed }) => [
              styles.toggle,
              { minHeight: theme.minTouchTarget, minWidth: theme.minTouchTarget },
              pressed && styles.pressed,
            ]}>
            <AppText variant="bodyStrong" color="textPrimary">
              {isPasswordVisible ? 'Hide' : 'Show'}
            </AppText>
          </Pressable>
        )}
      </View>
      {error ? (
        <AppText variant="caption" color="negative" nativeID={errorId} accessibilityRole="alert" accessibilityLiveRegion="polite">
          {`[!] ${error}`}
        </AppText>
      ) : helperText ? (
        <AppText variant="caption" color="textSecondary">
          {helperText}
        </AppText>
      ) : null}
    </View>
  );
});

const styles = StyleSheet.create({
  container: { width: '100%', gap: 6 },
  wrapper: { flexDirection: 'row', alignItems: 'center' },
  input: { flex: 1, paddingVertical: 10 },
  toggle: { justifyContent: 'center', alignItems: 'center', paddingHorizontal: 8 },
  pressed: { opacity: 0.6 },
});
