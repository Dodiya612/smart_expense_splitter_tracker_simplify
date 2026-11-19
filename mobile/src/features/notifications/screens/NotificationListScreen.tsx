/**
 * Notification centre (T-36 / US-38): newest first, unread clearly marked, tap to open
 * the related group or balances, mark all read, settings, and loading / empty / error states.
 */

import React from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { GroupScreenHeader } from '@/features/groups/components/GroupScreenHeader';
import { useTheme } from '@/theme';
import { NotificationRow } from '../components/NotificationRow';
import { NotificationStateView } from '../components/NotificationStateView';
import { useNotifications } from '../hooks/useNotifications';
import type { NotificationItem } from '../types';
import { notificationTarget } from '../utils/parseNotifications';

export function NotificationListScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const n = useNotifications();

  const open = (item: NotificationItem) => {
    void n.markRead(item.id);
    const target = notificationTarget(item);
    if (target) router.push(target as Href);
  };

  const frame = {
    flex: 1,
    backgroundColor: theme.colors.background,
    paddingTop: insets.top,
    paddingHorizontal: theme.spacing.lg,
  } as const;

  const header = (
    <View style={{ gap: theme.spacing.sm, marginBottom: theme.spacing.md }}>
      <GroupScreenHeader
        title="Notifications"
        subtitle={n.unreadCount > 0 ? `${n.unreadCount} unread` : 'All caught up'}
      />
      <View style={[styles.actions, { gap: theme.spacing.sm }]}>
        <Button
          label="Mark all as read"
          variant="outline"
          disabled={n.unreadCount === 0}
          style={styles.flex}
          onPress={() => void n.markAllRead()}
        />
        <Button
          label="Settings"
          variant="outline"
          style={styles.flex}
          onPress={() => router.push('/notification-settings' as Href)}
        />
      </View>
      {n.actionError ? (
        <AppText variant="small" color="negative" accessibilityRole="alert">
          {n.actionError}
        </AppText>
      ) : null}
    </View>
  );

  if (n.isLoading && !n.items) {
    return (
      <View style={frame}>
        <GroupScreenHeader title="Notifications" />
        <NotificationStateView kind="loading" title="Loading your notifications" />
      </View>
    );
  }

  if (n.error && !n.items) {
    return (
      <View style={frame}>
        <GroupScreenHeader title="Notifications" />
        <NotificationStateView
          kind="error"
          title="Could not load notifications"
          message={n.error.message}
          actionLabel="Try again"
          onAction={n.retry}
        />
      </View>
    );
  }

  return (
    <View style={frame}>
      <FlatList
        data={n.items ?? []}
        keyExtractor={(item) => item.id}
        ListHeaderComponent={header}
        renderItem={({ item }) => <NotificationRow item={item} onPress={open} />}
        ItemSeparatorComponent={() => <View style={{ height: theme.spacing.sm }} />}
        ListEmptyComponent={
          <NotificationStateView
            kind="empty"
            title="No notifications yet"
            message="Group activity such as new expenses, settlements and invitations will show up here."
          />
        }
        ListFooterComponent={
          n.isLoadingMore ? (
            <ActivityIndicator color={theme.colors.primary} style={{ margin: theme.spacing.lg }} />
          ) : n.hasMore ? (
            <Button
              label="Load older"
              variant="outline"
              style={{ marginVertical: theme.spacing.lg }}
              onPress={() => void n.loadMore()}
            />
          ) : null
        }
        refreshControl={
          <RefreshControl
            refreshing={n.isRefreshing}
            onRefresh={() => void n.refresh()}
            tintColor={theme.colors.primary}
          />
        }
        contentContainerStyle={{ paddingBottom: Math.max(insets.bottom, theme.spacing.lg) + theme.spacing.lg }}
        showsVerticalScrollIndicator={false}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  actions: { flexDirection: 'row' },
  flex: { flex: 1 },
});
