/**
 * Groups tab entry point – hosts the GroupBalancesScreen (T-33 / US-10).
 *
 * Provides primary access to group balances and settlements in the main tab navigation.
 */

import React from 'react';
import { GroupBalancesScreen } from '@/features/balances/screens/GroupBalancesScreen';

export default function GroupsTab() {
  return <GroupBalancesScreen />;
}
