/**
 * Group balances screen route (T-33 / US-10).
 *
 * Mounts GroupBalancesScreen with safe query parameter parsing.
 */

import React, { Suspense, lazy } from 'react';
import { useLocalSearchParams } from 'expo-router';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';
import { GroupBalancesSkeleton } from '@/features/balances/components/GroupBalancesSkeleton';

const GroupBalancesScreen = lazy(() =>
  import('@/features/balances/screens/GroupBalancesScreen').then((module) => ({
    default: module.GroupBalancesScreen,
  }))
);

export default function GroupBalancesRoute() {
  const { groupId, groupName } = useLocalSearchParams<{ groupId?: string; groupName?: string }>();
  return (
    <RouteErrorBoundary routeName="Group Balances">
      <Suspense fallback={<GroupBalancesSkeleton />}>
        <GroupBalancesScreen groupId={groupId} groupName={groupName} />
      </Suspense>
    </RouteErrorBoundary>
  );
}
