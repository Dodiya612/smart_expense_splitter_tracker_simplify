import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';

export interface ChangePasswordSuccessProps {
  message: string;
  onDone: () => void;
  onViewNotifications: () => void;
}

/** In-app confirmation shown right after a successful password change (T-50). */
export function ChangePasswordSuccess({ message, onDone, onViewNotifications }: ChangePasswordSuccessProps) {
  const theme = useTheme();
  return (
    <AppCard>
      <View
        style={[styles.content, { gap: theme.spacing.md }]}
        accessibilityRole="alert"
        accessibilityLiveRegion="polite">
        <Ionicons name="shield-checkmark-outline" size={32} color={theme.colors.positive.text} />
        <AppText variant="heading" accessibilityRole="header">
          Password changed
        </AppText>
        <AppText variant="body" color="textSecondary" style={styles.centered}>
          {message}
        </AppText>
        <AppText variant="small" color="textSecondary" style={styles.centered}>
          A security notice has been added to your notifications.
        </AppText>
        <View style={[styles.actions, { gap: theme.spacing.sm }]}>
          <Button label="Done" fullWidth onPress={onDone} />
          <Button label="View notifications" variant="outline" fullWidth onPress={onViewNotifications} />
        </View>
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  content: { alignItems: 'center' },
  centered: { textAlign: 'center' },
  actions: { width: '100%' },
});
