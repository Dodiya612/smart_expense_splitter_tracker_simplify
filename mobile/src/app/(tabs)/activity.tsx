/**
 * Activity Tab Route — Hosts SpendingInsightsScreen (T-43 / US-12).
 *
 * Mapped to the 'Activity' tab in the main AppTabBar navigation.
 */

import React from 'react';
import { SpendingInsightsScreen } from '@/features/analytics/screens/SpendingInsightsScreen';

export default function ActivityTabRoute() {
  return <SpendingInsightsScreen />;
}
