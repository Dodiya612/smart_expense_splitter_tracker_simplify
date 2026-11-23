/**
 * Groups tab (T-29 / US-17): my groups, plus Create group and Join with code.
 */

import React from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import { GroupListItem } from '../components/GroupListItem';
import { GroupStateView } from '../components/GroupStateView';
import { useGroups } from '../hooks/useGroups';
import type { GroupSummary } from '../types';

export function GroupListScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { groups, isLoading, isRefreshing, error, refresh, retry } = useGroups();

  const openCreate = () => router.push('/groups/create' as Href);
  const openJoin = () => router.push('/join' as Href);
  const openGroup = (group: GroupSummary) =>
    router.push({ pathname: '/groups/[id]', params: { id: group.id } } as Href);

  const header = (
    <View style={{ gap: theme.spacing.md, marginBottom: theme.spacing.md }}>
      <AppText variant="title" accessibilityRole="header">
        Groups
      </AppText>
      <View style={[styles.actions, { gap: theme.spacing.sm }]}>
        <Button label="Create group" style={styles.flex} onPress={openCreate} />
        <Button label="Join with code" variant="outline" style={styles.flex} onPress={openJoin} />
      </View>
    </View>
  );

  const padding = {
    paddingTop: insets.top + theme.spacing.md,
    paddingHorizontal: theme.spacing.lg,
  };

  if (isLoading && !groups) {
    return (
      <View style={[styles.root, padding, { backgroundColor: theme.colors.background }]}>
        <GroupStateView kind="loading" title="Loading your groups" />
      </View>
    );
  }

  if (error && !groups) {
    return (
      <View style={[styles.root, padding, { backgroundColor: theme.colors.background }]}>
        <GroupStateView
          kind="error"
          title="Could not load your groups"
          message={error.message}
          actionLabel="Try again"
          onAction={retry}
        />
      </View>
    );
  }

  return (
    <FlatList
      style={[styles.root, { backgroundColor: theme.colors.background }]}
      contentContainerStyle={[
        styles.content,
        padding,
        { paddingBottom: insets.bottom + theme.spacing.xxxl, gap: theme.spacing.sm },
      ]}
      data={groups ?? []}
      keyExtractor={(g) => g.id}
      renderItem={({ item }) => <GroupListItem group={item} onPress={openGroup} />}
      ListHeaderComponent={header}
      ListEmptyComponent={
        <GroupStateView
          kind="empty"
          title="No groups yet"
          message="Create a group for your flat, trip, friends or family, or join one with an invite code."
        />
      }
      refreshControl={
        <RefreshControl refreshing={isRefreshing} onRefresh={refresh} tintColor={theme.colors.primary} />
      }
      accessibilityLabel="Your groups"
    />
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { flexGrow: 1 },
  actions: { flexDirection: 'row' },
  flex: { flex: 1 },
});
