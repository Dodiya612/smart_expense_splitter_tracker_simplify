/** Group screen route (T-29 / US-17): /groups/<groupId>. */

import React from 'react';
import { useLocalSearchParams } from 'expo-router';
import { GroupDetailScreen } from '@/features/groups/screens/GroupDetailScreen';

export default function GroupDetailRoute() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  return <GroupDetailScreen groupId={id} />;
}
