import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { useUnreadCount } from '../hooks/useUnreadCount';
import { badgeLabel } from '../utils/parseNotifications';

/** Bell with an unread-count badge for the Home header (T-36 / US-38). */
export function NotificationBell() {
  const theme = useTheme();
  const { count } = useUnreadCount();
  const label = badgeLabel(count);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={count > 0 ? `Notifications, ${count} unread` : 'Notifications'}
      accessibilityHint="Opens your notifications"
      onPress={() => router.push('/notifications' as Href)}
      hitSlop={theme.spacing.xs}
      style={({ pressed }) => [
        styles.button,
        {
          width: theme.minTouchTarget,
          height: theme.minTouchTarget,
          borderRadius: theme.radii.pill,
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
        },
        pressed && styles.pressed,
      ]}>
      <Ionicons name="notifications-outline" size={22} color={theme.colors.textPrimary} />
      {label ? (
        <View
          style={[
            styles.badge,
            {
              backgroundColor: theme.colors.primary,
              borderColor: theme.colors.surface,
              borderRadius: theme.radii.pill,
              paddingHorizontal: theme.spacing.xs,
            },
          ]}>
          <AppText variant="caption" color="textOnPrimary" style={styles.badgeText}>
            {label}
          </AppText>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: { alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
  pressed: { opacity: 0.6 },
  badge: {
    position: 'absolute',
    top: -2,
    right: -2,
    minWidth: 20,
    height: 20,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
  },
  badgeText: { fontSize: 11, lineHeight: 14 },
});
