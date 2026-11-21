/**
 * Groups tab entry point – hosts the GroupBalancesScreen (T-33 / US-10).
 *
 * Provides primary access to group balances and settlements in the main tab navigation.
 */

import React, { Suspense, lazy } from 'react';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';
import { GroupBalancesSkeleton } from '@/features/balances/components/GroupBalancesSkeleton';

const GroupBalancesScreen = lazy(() =>
  import('@/features/balances/screens/GroupBalancesScreen').then((module) => ({
    default: module.GroupBalancesScreen,
  }))
);

export default function GroupsTab() {
  return (
    <RouteErrorBoundary routeName="Groups">
      <Suspense fallback={<GroupBalancesSkeleton />}>
        <GroupBalancesScreen />
      </Suspense>
    </RouteErrorBoundary>
  );
}
