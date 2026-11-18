/**
 * Groups tab (T-29 / US-17): list of my groups with Create group and Join with code.
 * Group balances (T-33) open from each group's screen via /group-balances.
 */

import React from 'react';
import { GroupListScreen } from '@/features/groups/screens/GroupListScreen';

export default function GroupsTab() {
  return <GroupListScreen />;
}
