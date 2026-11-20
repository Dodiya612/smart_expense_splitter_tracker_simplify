import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { NotificationItem } from '../types';
import { formatRelativeTime } from '../utils/parseNotifications';

type IconName = React.ComponentProps<typeof Ionicons>['name'];

const KIND_ICONS: Record<string, IconName> = {
  group_expense_created: 'receipt-outline',
  group_expense_updated: 'create-outline',
  group_expense_deleted: 'trash-outline',
  settlement_recorded: 'swap-horizontal-outline',
  member_joined: 'person-add-outline',
  invitation_received: 'mail-outline',
  invitation_accepted: 'checkmark-circle-outline',
  invitation_declined: 'close-circle-outline',
  member_removed: 'person-remove-outline',
  member_left: 'exit-outline',
  password_changed: 'lock-closed-outline',
};

export interface NotificationRowProps {
  item: NotificationItem;
  onPress: (item: NotificationItem) => void;
}

/** One notification. Unread is shown with a dot, bold title and a tinted card, plus the spoken word "unread". */
export function NotificationRow({ item, onPress }: NotificationRowProps) {
  const theme = useTheme();
  const time = formatRelativeTime(item.createdAt);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${item.isRead ? '' : 'Unread. '}${item.title}. ${item.body} ${time}`}
      accessibilityHint="Opens the related item"
      onPress={() => onPress(item)}
      style={({ pressed }) => [
        styles.row,
        {
          minHeight: theme.minTouchTarget,
          padding: theme.spacing.md,
          gap: theme.spacing.md,
          borderRadius: theme.radii.lg,
          borderColor: theme.colors.border,
          backgroundColor: item.isRead ? theme.colors.surfaceMuted : theme.colors.surface,
        },
        !item.isRead && theme.shadows.card,
        pressed && styles.pressed,
      ]}>
      <View
        style={[
          styles.icon,
          {
            width: theme.minTouchTarget,
            height: theme.minTouchTarget,
            borderRadius: theme.radii.pill,
            backgroundColor: item.isRead ? theme.colors.surface : theme.colors.info.soft,
          },
        ]}>
        <Ionicons
          name={KIND_ICONS[item.kind] ?? 'notifications-outline'}
          size={22}
          color={item.isRead ? theme.colors.textSecondary : theme.colors.info.text}
        />
      </View>
      <View style={styles.text}>
        <View style={[styles.titleRow, { gap: theme.spacing.sm }]}>
          <AppText
            variant={item.isRead ? 'body' : 'bodyStrong'}
            numberOfLines={1}
            style={styles.title}>
            {item.title}
          </AppText>
          {!item.isRead ? (
            <View
              style={[
                styles.dot,
                { backgroundColor: theme.colors.info.text, borderRadius: theme.radii.pill },
              ]}
            />
          ) : null}
        </View>
        <AppText variant="small" color="textSecondary" numberOfLines={3}>
          {item.body}
        </AppText>
        <AppText variant="caption" color="textSecondary">
          {time}
        </AppText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-start', borderWidth: 1 },
  pressed: { opacity: 0.7 },
  icon: { alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1, gap: 2 },
  titleRow: { flexDirection: 'row', alignItems: 'center' },
  title: { flexShrink: 1 },
  dot: { width: 8, height: 8 },
});
