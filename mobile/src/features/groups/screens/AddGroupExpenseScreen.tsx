/**
 * Add group expense (T-31 / US-18, US-19): amount, description, category, who
 * paid, who is in, and the split editor with a live preview. "Save expense" stays
 * disabled until the split adds up, so an unbalanced split cannot be saved.
 */

import React from 'react';
import { Href, router } from 'expo-router';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { useAuth } from '@/features/auth/context/AuthContext';
import { GroupScreenHeader } from '../components/GroupScreenHeader';
import { GroupStateView } from '../components/GroupStateView';
import { useGroupDetail } from '../hooks/useGroupDetail';
import { AddGroupExpenseForm } from './AddGroupExpenseForm';

export interface AddGroupExpenseScreenProps {
  groupId?: string;
}

export function AddGroupExpenseScreen({ groupId }: AddGroupExpenseScreenProps) {
  const { user } = useAuth();
  const { group, isLoading, error, retry } = useGroupDetail(groupId);

  if (isLoading && !group) {
    return (
      <ScreenContainer>
        <GroupScreenHeader title="Add group expense" />
        <GroupStateView kind="loading" title="Loading group members" />
      </ScreenContainer>
    );
  }

  if (!group) {
    return (
      <ScreenContainer>
        <GroupScreenHeader title="Add group expense" />
        <GroupStateView
          kind="error"
          title="Could not load this group"
          message={error?.message}
          actionLabel="Try again"
          onAction={retry}
          secondaryLabel="Back to groups"
          onSecondary={() => router.replace('/(tabs)/groups' as Href)}
        />
      </ScreenContainer>
    );
  }

  return <AddGroupExpenseForm group={group} currentUserId={user?.id} />;
}
