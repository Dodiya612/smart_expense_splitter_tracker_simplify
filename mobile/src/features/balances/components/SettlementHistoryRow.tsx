/**
 * One recorded settlement (T-33 / US-10), e.g. "Blair settled ₹1,000.00 with you".
 * A settlement is a record of a repayment made outside the app.
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { SettlementRecord } from '../types';
import { settlementLabel } from '../utils/balanceLabels';

export interface SettlementHistoryRowProps {
  readonly record: SettlementRecord;
  readonly currentUserId: string | undefined;
  readonly nameOf: (userId: string) => string;
}

function formatDate(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

export function SettlementHistoryRow({ record, currentUserId, nameOf }: SettlementHistoryRowProps) {
  const theme = useTheme();
  const label = settlementLabel(record, currentUserId, nameOf);
  const detail = [
    `Recorded for ${formatDate(record.settlementDate)}`,
    record.isPartial ? 'Part payment' : null,
    record.notes,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <AppCard
      accessibilityLabel={`${label}. ${detail}`}
      style={[styles.card, { borderColor: theme.colors.border, padding: theme.spacing.sm, gap: theme.spacing.xs }]}
    >
      <View style={[styles.row, { gap: theme.spacing.sm }]}>
        <Ionicons name="checkmark-done-outline" size={18} color={theme.colors.textSecondary} />
        <AppText variant="body" color="textPrimary" style={styles.flex}>
          {label}
        </AppText>
      </View>
      <AppText variant="caption" color="textSecondary">
        {detail}
      </AppText>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  flex: {
    flex: 1,
  },
});
