/**
 * Route: /scan-bill – take or choose a bill photo and review it (T-54 / US-16).
 * Opened from the add-expense form. On success it replaces itself with
 * /add-expense?draft=… so the user confirms the pre-filled expense.
 */

import React from 'react';
import { ScanBillScreen } from '@/features/bills/screens/ScanBillScreen';

export default function ScanBillRoute() {
  return <ScanBillScreen />;
}
