/**
 * Group balances screen route (T-33 / US-10).
 *
 * Mounts GroupBalancesScreen with safe query parameter parsing.
 */

import React from 'react';
import { useLocalSearchParams } from 'expo-router';
import { GroupBalancesScreen } from '@/features/balances/screens/GroupBalancesScreen';

export default function GroupBalancesRoute() {
  const { groupId, groupName } = useLocalSearchParams<{ groupId?: string; groupName?: string }>();
  return <GroupBalancesScreen groupId={groupId} groupName={groupName} />;
}
