import React from 'react';
import { StyleSheet, View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';

export interface AuthErrorBannerProps {
  message: string;
  isRetryable?: boolean;
  onRetry?: () => void;
  actionLabel?: string;
  onAction?: () => void;
}

export function AuthErrorBanner({
  message,
  isRetryable = false,
  onRetry,
  actionLabel,
  onAction,
}: AuthErrorBannerProps) {
  const theme = useTheme();

  return (
    <View
      accessibilityRole="alert"
      accessibilityLiveRegion="assertive"
      style={[
        styles.banner,
        {
          backgroundColor: theme.colors.negative.soft,
          borderColor: theme.colors.negative.text,
          borderRadius: theme.radii.md,
          padding: theme.spacing.md,
          gap: theme.spacing.sm,
        },
      ]}>
      <AppText variant="small" color="negative">
        {`[!] ${message}`}
      </AppText>
      {isRetryable && onRetry && (
        <Button
          label="Try again"
          variant="outline"
          onPress={onRetry}
          accessibilityLabel="Retry submission"
        />
      )}
      {!isRetryable && actionLabel && onAction && (
        <Button
          label={actionLabel}
          variant="outline"
          onPress={onAction}
          accessibilityLabel={actionLabel}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    width: '100%',
    borderWidth: 1,
  },
});
