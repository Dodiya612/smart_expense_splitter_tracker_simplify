import React from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';

export type GroupStateKind = 'loading' | 'error' | 'empty';

export interface GroupStateViewProps {
  kind: GroupStateKind;
  title: string;
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
}

/** Loading, error (with retry) and empty states for the groups screens (T-29). */
export function GroupStateView({
  kind,
  title,
  message,
  actionLabel,
  onAction,
  secondaryLabel,
  onSecondary,
}: GroupStateViewProps) {
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
          name={kind === 'error' ? 'alert-circle-outline' : 'people-outline'}
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
      {secondaryLabel && onSecondary ? (
        <Button label={secondaryLabel} variant="outline" fullWidth onPress={onSecondary} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  center: { textAlign: 'center' },
});
