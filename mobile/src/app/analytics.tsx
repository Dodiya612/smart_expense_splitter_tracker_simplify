/**
 * Dedicated /analytics Route (T-43 / US-12).
 *
 * Mapped to the <Stack.Screen name="analytics" /> declared in root _layout.tsx.
 */

import React from 'react';
import { useLocalSearchParams } from 'expo-router';
import { SpendingInsightsScreen } from '@/features/analytics/screens/SpendingInsightsScreen';

export default function AnalyticsRoute() {
  const { groupId } = useLocalSearchParams<{ groupId?: string }>();
  return <SpendingInsightsScreen groupId={groupId} />;
}
