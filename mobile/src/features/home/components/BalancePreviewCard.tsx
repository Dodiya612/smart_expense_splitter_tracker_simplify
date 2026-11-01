import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { BalanceSummary } from '../types';
import { formatPaiseToInr } from '../utils/dashboardSummary';

export interface BalancePreviewCardProps {
  balances: BalanceSummary;
}

export function BalancePreviewCard({ balances }: BalancePreviewCardProps) {
  const theme = useTheme();

  const formattedOwed = `+${formatPaiseToInr(balances.youAreOwedPaise)}`;
  const formattedOwe = `-${formatPaiseToInr(balances.youOwePaise)}`;
  const hasZeroBalances = balances.youAreOwedPaise === 0 && balances.youOwePaise === 0;

  const a11yLabel = hasZeroBalances
    ? 'Balances overview. No balances to show yet.'
    : `Balances overview. Sample data: you are owed ${formattedOwed}, you owe ${formattedOwe}.`;

  return (
    <AppCard
      accessibilityRole="summary"
      accessibilityLabel={a11yLabel}
      style={{ gap: theme.spacing.sm }}
    >
      {/* ── Card Header ────────────────────────────────────────── */}
      <View style={styles.cardHeader}>
        <View style={[styles.titleRow, { gap: theme.spacing.xs }]}>
          <Ionicons name="people-outline" size={18} color={theme.colors.primary} />
          <AppText variant="bodyStrong" color="textPrimary">
            Balances
          </AppText>
          <View
            style={[
              styles.badge,
              {
                backgroundColor: theme.colors.surfaceMuted,
                borderRadius: theme.radii.sm,
                borderColor: theme.colors.border,
                paddingHorizontal: theme.spacing.xs + 2,
                paddingVertical: 2,
              },
            ]}
          >
            <AppText variant="caption" color="textSecondary">
              Sample
            </AppText>
          </View>
        </View>
      </View>

      {/* ── Balances Content ──────────────────────────────────── */}
      {hasZeroBalances ? (
        <View style={[styles.emptyContainer, { paddingVertical: theme.spacing.xs }]}>
          <AppText variant="small" color="textSecondary">
            No balances to show yet.
          </AppText>
        </View>
      ) : (
        <View style={[styles.balanceGrid, { gap: theme.spacing.sm }]}>
          {/* You are owed tile */}
          <View
            style={[
              styles.balanceTile,
              {
                backgroundColor: theme.colors.positive.soft,
                borderRadius: theme.radii.md,
                padding: theme.spacing.sm,
              },
            ]}
          >
            <AppText variant="caption" color="positive">
              You are owed
            </AppText>
            <AppText variant="money" color="positive" numberOfLines={1}>
              {formattedOwed}
            </AppText>
          </View>

          {/* You owe tile */}
          <View
            style={[
              styles.balanceTile,
              {
                backgroundColor: theme.colors.negative.soft,
                borderRadius: theme.radii.md,
                padding: theme.spacing.sm,
              },
            ]}
          >
            <AppText variant="caption" color="negative">
              You owe
            </AppText>
            <AppText variant="money" color="negative" numberOfLines={1}>
              {formattedOwe}
            </AppText>
          </View>
        </View>
      )}

      {/* ── Card Footer ────────────────────────────────────────── */}
      <View style={styles.cardFooter}>
        <AppText variant="caption" color="textSecondary">
          Demo estimates · Real ledger balance calculation will sync in a future phase
        </AppText>
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  badge: {
    borderWidth: 1,
  },
  balanceGrid: {
    flexDirection: 'row',
    alignItems: 'stretch',
    flexWrap: 'wrap',
  },
  balanceTile: {
    flex: 1,
    minWidth: 120,
    gap: 4,
  },
  emptyContainer: {
    alignItems: 'flex-start',
  },
  cardFooter: {
    marginTop: 2,
  },
});
