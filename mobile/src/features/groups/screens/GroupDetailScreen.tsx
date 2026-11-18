/**
 * Group screen (T-29 / US-17): group info, invite card for admins, member list,
 * a link to the group's balances (T-33), Add group expense (T-31) and Leave group (T-35).
 */

import React from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/features/auth/context/AuthContext';
import { useTheme } from '@/theme';
import { GroupScreenHeader } from '../components/GroupScreenHeader';
import { GroupStateView } from '../components/GroupStateView';
import { InviteCodeCard } from '../components/InviteCodeCard';
import { LeaveGroupSection } from '../components/LeaveGroupSection';
import { MemberListItem } from '../components/MemberListItem';
import { useGroupDetail } from '../hooks/useGroupDetail';
import { groupTypeInfo, isAdminRole, memberCountLabel } from '../utils/groupDisplay';

export interface GroupDetailScreenProps {
  groupId?: string;
}

export function GroupDetailScreen({ groupId }: GroupDetailScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const { group, isLoading, isRefreshing, error, refresh, retry } = useGroupDetail(groupId);

  const shell = [
    styles.root,
    { backgroundColor: theme.colors.background, paddingTop: insets.top, paddingHorizontal: theme.spacing.lg },
  ];

  if (isLoading && !group) {
    return (
      <View style={shell}>
        <GroupScreenHeader title="Group" />
        <GroupStateView kind="loading" title="Loading group" />
      </View>
    );
  }

  if (!group) {
    const notFound = error?.code === 'NOT_FOUND';
    return (
      <View style={shell}>
        <GroupScreenHeader title="Group" />
        <GroupStateView
          kind="error"
          title={notFound ? 'Group not found' : 'Could not load this group'}
          message={notFound ? 'It may have been deleted, or you are not a member.' : error?.message}
          actionLabel={notFound ? undefined : 'Try again'}
          onAction={notFound ? undefined : retry}
          secondaryLabel="Back to groups"
          onSecondary={() => router.replace('/(tabs)/groups' as Href)}
        />
      </View>
    );
  }

  const type = groupTypeInfo(group.type);
  const openAddExpense = () =>
    router.push({ pathname: '/groups/add-expense', params: { groupId: group.id } } as Href);
  const openBalances = () =>
    router.push({
      pathname: '/group-balances',
      params: { groupId: group.id, groupName: group.name },
    } as Href);

  const header = (
    <View style={{ gap: theme.spacing.md, marginBottom: theme.spacing.sm }}>
      <GroupScreenHeader
        title={group.name}
        subtitle={`${type.label} · ${memberCountLabel(group.members.length)}`}
      />
      {group.description ? (
        <AppText variant="body" color="textSecondary">
          {group.description}
        </AppText>
      ) : null}
      {isAdminRole(group.currentUserRole) ? (
        <InviteCodeCard groupId={group.id} groupName={group.name} />
      ) : (
        <AppText variant="small" color="textSecondary">
          To invite someone, ask a group admin for an invite code.
        </AppText>
      )}
      <Button label="Add group expense" fullWidth onPress={openAddExpense} />
      <Button label="View balances" variant="secondary" fullWidth onPress={openBalances} />
      <AppText variant="bodyStrong" accessibilityRole="header" style={{ marginTop: theme.spacing.sm }}>
        {`Members (${group.members.length})`}
      </AppText>
    </View>
  );

  return (
    <FlatList
      style={shell}
      contentContainerStyle={{ paddingBottom: insets.bottom + theme.spacing.xxxl }}
      data={group.members}
      keyExtractor={(m) => m.userId}
      renderItem={({ item }) => <MemberListItem member={item} isCurrentUser={item.userId === user?.id} />}
      ListHeaderComponent={header}
      ListFooterComponent={<LeaveGroupSection group={group} currentUserId={user?.id} />}
      ListEmptyComponent={
        <AppText variant="small" color="textSecondary">
          No active members.
        </AppText>
      }
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl refreshing={isRefreshing} onRefresh={refresh} tintColor={theme.colors.primary} />
      }
      accessibilityLabel="Group members"
    />
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
});
