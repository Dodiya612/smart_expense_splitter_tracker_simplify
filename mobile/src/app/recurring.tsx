/**
 * Route: /recurring – my recurring expenses (T-45 / US-14).
 * Opened from the Expenses tab and from recurring-expense notifications.
 */

import React from 'react';
import { RecurringListScreen } from '@/features/recurring/screens/RecurringListScreen';

export default function RecurringRoute() {
  return <RecurringListScreen />;
}
