import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  PressableProps,
  StyleProp,
  StyleSheet,
  ViewStyle,
} from 'react-native';
import { useTheme } from '@/theme';
import { AppText } from './AppText';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'destructive';

export interface ButtonProps extends Omit<PressableProps, 'style' | 'children'> {
  label: string;
  variant?: ButtonVariant;
  disabled?: boolean;
  loading?: boolean;
  fullWidth?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function Button({
  label,
  variant = 'primary',
  disabled = false,
  loading = false,
  fullWidth = false,
  style,
  accessibilityLabel,
  accessibilityHint,
  onPress,
  ...restProps
}: ButtonProps) {
  const theme = useTheme();
  const isInteractive = !disabled && !loading;

  const getVariantStyles = (pressed: boolean): ViewStyle => {
    switch (variant) {
      case 'primary':
        return {
          backgroundColor: pressed ? theme.colors.primaryPressed : theme.colors.primary,
          ...(isInteractive && !pressed
            ? theme.shadows.button
            : { elevation: 0, shadowOpacity: 0 }),
        };
      case 'destructive':
        return {
          backgroundColor: theme.colors.negative.text,
          opacity: pressed ? 0.88 : 1,
        };
      case 'secondary':
        return {
          backgroundColor: pressed ? theme.colors.border : theme.colors.surfaceMuted,
        };
      case 'outline':
        return {
          backgroundColor: pressed ? theme.colors.surfaceMuted : 'transparent',
          borderWidth: 1.5,
          borderColor: theme.colors.borderStrong,
        };
    }
  };

  const getTextColor = () => {
    switch (variant) {
      case 'primary':
      case 'destructive':
        return 'textOnPrimary' as const;
      case 'secondary':
      case 'outline':
        return 'textPrimary' as const;
    }
  };

  const getSpinnerColor = () => {
    switch (variant) {
      case 'primary':
      case 'destructive':
        return theme.colors.textOnPrimary;
      case 'secondary':
      case 'outline':
        return theme.colors.textPrimary;
    }
  };

  const a11yLabel = loading
    ? `${accessibilityLabel ?? label}, loading`
    : (accessibilityLabel ?? label);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={a11yLabel}
      accessibilityHint={accessibilityHint}
      accessibilityState={{
        disabled: !isInteractive,
        busy: loading,
      }}
      disabled={!isInteractive}
      onPress={isInteractive ? onPress : undefined}
      style={({ pressed }) => [
        styles.base,
        {
          minHeight: theme.minTouchTarget,
          borderRadius: theme.radii.md,
          paddingHorizontal: theme.spacing.lg,
          paddingVertical: theme.spacing.sm,
        },
        fullWidth && styles.fullWidth,
        getVariantStyles(pressed && isInteractive),
        disabled && !loading && styles.disabled,
        style,
      ]}
      {...restProps}>
      {loading ? (
        <ActivityIndicator size="small" color={getSpinnerColor()} />
      ) : (
        <AppText
          variant="bodyStrong"
          color={getTextColor()}
          style={styles.label}>
          {label}
        </AppText>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
  },
  fullWidth: {
    width: '100%',
  },
  label: {
    textAlign: 'center',
  },
  disabled: {
    opacity: 0.5,
  },
});
