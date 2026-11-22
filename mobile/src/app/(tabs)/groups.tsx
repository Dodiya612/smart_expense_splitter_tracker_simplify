/**
 * Groups tab (T-29 / US-17): list of my groups with Create group and Join with code.
 * Group balances (T-33) open from each group's screen via /group-balances.
 */

import React, { Suspense, lazy } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { RouteErrorBoundary } from '@/components/navigation/RouteErrorBoundary';

const GroupListScreen = lazy(() =>
  import('@/features/groups/screens/GroupListScreen').then((module) => ({
    default: module.GroupListScreen,
  }))
);

export default function GroupsTab() {
  return (
    <RouteErrorBoundary routeName="Groups">
      <Suspense
        fallback={
          <View
            style={{
              flex: 1,
              justifyContent: 'center',
              alignItems: 'center',
            }}
          >
            <ActivityIndicator size="large" />
          </View>
        }
      >
        <GroupListScreen />
      </Suspense>
    </RouteErrorBoundary>
  );
}