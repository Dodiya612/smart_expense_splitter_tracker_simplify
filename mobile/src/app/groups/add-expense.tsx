/** Add group expense route (T-31 / US-18, US-19): /groups/add-expense?groupId=<id>. */

import React from 'react';
import { useLocalSearchParams } from 'expo-router';
import { AddGroupExpenseScreen } from '@/features/groups/screens/AddGroupExpenseScreen';

export default function AddGroupExpenseRoute() {
  const { groupId } = useLocalSearchParams<{ groupId?: string }>();
  return <AddGroupExpenseScreen groupId={typeof groupId === 'string' ? groupId : undefined} />;
}
