import React from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';

export interface NotificationStateViewProps {
  kind: 'loading' | 'error' | 'empty';
  title: string;
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
}

/** Loading, error (with retry) and empty states for the notification screens (T-36). */
export function NotificationStateView({
  kind,
  title,
  message,
  actionLabel,
  onAction,
}: NotificationStateViewProps) {
  const theme = useTheme();

  return (
    <View
      style={[styles.root, { padding: theme.spacing.xl, gap: theme.spacing.sm }]}
      accessibilityRole={kind === 'error' ? 'alert' : undefined}
      accessibilityLiveRegion="polite">
      {kind === 'loading' ? (
        <ActivityIndicator size="large" color={theme.colors.primary} />
      ) : (
        <Ionicons
          name={kind === 'error' ? 'alert-circle-outline' : 'notifications-off-outline'}
          size={48}
          color={kind === 'error' ? theme.colors.negative.text : theme.colors.textSecondary}
        />
      )}
      <AppText variant="heading" style={styles.center}>
        {title}
      </AppText>
      {message ? (
        <AppText variant="body" color="textSecondary" style={styles.center}>
          {message}
        </AppText>
      ) : null}
      {actionLabel && onAction ? (
        <Button label={actionLabel} fullWidth onPress={onAction} style={{ marginTop: theme.spacing.md }} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  center: { textAlign: 'center' },
});
