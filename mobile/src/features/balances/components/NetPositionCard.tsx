/**
 * NetPositionCard component (T-33 / US-10).
 *
 * Displays:
 * - Net balance standing across the group.
 * - Breakdowns of "You are owed" and "You owe" with +/- signs and text labels (never colour alone).
 * - Amounts through the shared INR formatter (src/utils/money.ts).
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { formatPaise } from '@/utils/money';
import { myPositionLabel } from '../utils/balanceLabels';

export interface NetPositionCardProps {
  netBalancePaise: number;
  youAreOwedPaise: number;
  youOwePaise: number;
  currency?: string;
}


export function NetPositionCard({
  netBalancePaise,
  youAreOwedPaise,
  youOwePaise,
}: NetPositionCardProps) {
  const theme = useTheme();

  const isNetCreditor = netBalancePaise > 0;
  const isNetDebtor = netBalancePaise < 0;
  const isSettled = netBalancePaise === 0;

  const netColor = isNetCreditor
    ? theme.colors.positive.text
    : isNetDebtor
      ? theme.colors.negative.text
      : theme.colors.textPrimary;

  const netPrefix = isNetCreditor ? '+' : isNetDebtor ? '-' : '';

  const a11ySummary = isSettled
    ? 'All balances in this group are settled.'
    : `Net standing: you are owed ${formatPaise(youAreOwedPaise)}, and you owe ${formatPaise(youOwePaise)}.`;

  return (
    <AppCard
      accessibilityRole="summary"
      accessibilityLabel={a11ySummary}
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          gap: theme.spacing.md,
        },
      ]}
    >
      {/* ── Top Header ────────────────────────────────────────── */}
      <View style={styles.headerRow}>
        <View style={[styles.titleWithIcon, { gap: theme.spacing.sm }]}>
          <Ionicons
            name="wallet-outline"
            size={20}
            color={theme.colors.primary}
          />
          <AppText variant="bodyStrong" color="textPrimary">
            Your position in this group
          </AppText>
        </View>

        <View
          style={[
            styles.statusBadge,
            {
              backgroundColor: isNetCreditor
                ? theme.colors.positive.soft
                : isNetDebtor
                  ? theme.colors.negative.soft
                  : theme.colors.surfaceMuted,
              borderRadius: theme.radii.pill,
              paddingHorizontal: theme.spacing.sm,
              paddingVertical: theme.spacing.xs,
              borderColor: isNetCreditor
                ? theme.colors.positive.fill
                : isNetDebtor
                  ? theme.colors.negative.fill
                  : theme.colors.border,
            },
          ]}
        >
          <AppText
            variant="caption"
            style={{
              color: isNetCreditor
                ? theme.colors.positive.text
                : isNetDebtor
                  ? theme.colors.negative.text
                  : theme.colors.textSecondary,
              fontFamily: theme.fontFamily.semibold,
            }}
          >
            {myPositionLabel(netBalancePaise)}
          </AppText>
        </View>
      </View>

      {/* ── Net Big Number ────────────────────────────────────── */}
      <View style={{ marginVertical: theme.spacing.xs }}>
        <AppText
          variant="moneyLarge"
          style={{ color: netColor }}
          accessibilityLabel={`Net position ${netPrefix}${formatPaise(Math.abs(netBalancePaise))}`}
        >
          {netPrefix}
          {formatPaise(Math.abs(netBalancePaise))}
        </AppText>
      </View>

      {/* ── Two-Column Breakdown ──────────────────────────────── */}
      <View
        style={[
          styles.breakdownRow,
          {
            borderTopColor: theme.colors.border,
            paddingTop: theme.spacing.sm,
            gap: theme.spacing.md,
          },
        ]}
      >
        {/* You are owed tile */}
        <View
          style={[
            styles.breakdownTile,
            {
              backgroundColor: theme.colors.positive.soft,
              borderRadius: theme.radii.md,
              padding: theme.spacing.sm,
            },
          ]}
        >
          <View style={[styles.tileHeader, { gap: theme.spacing.xs }]}>
            <Ionicons
              name="arrow-down-circle"
              size={16}
              color={theme.colors.positive.text}
            />
            <AppText variant="caption" style={{ color: theme.colors.positive.text }}>
              You are owed
            </AppText>
          </View>
          <AppText
            variant="money"
            style={{ color: theme.colors.positive.text, marginTop: theme.spacing.xs }}
          >
            +{formatPaise(youAreOwedPaise)}
          </AppText>
        </View>

        {/* You owe tile */}
        <View
          style={[
            styles.breakdownTile,
            {
              backgroundColor: theme.colors.negative.soft,
              borderRadius: theme.radii.md,
              padding: theme.spacing.sm,
            },
          ]}
        >
          <View style={[styles.tileHeader, { gap: theme.spacing.xs }]}>
            <Ionicons
              name="arrow-up-circle"
              size={16}
              color={theme.colors.negative.text}
            />
            <AppText variant="caption" style={{ color: theme.colors.negative.text }}>
              You owe
            </AppText>
          </View>
          <AppText
            variant="money"
            style={{ color: theme.colors.negative.text, marginTop: theme.spacing.xs }}
          >
            -{formatPaise(youOwePaise)}
          </AppText>
        </View>
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  titleWithIcon: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusBadge: {
    borderWidth: 1,
  },
  breakdownRow: {
    flexDirection: 'row',
    borderTopWidth: 1,
  },
  breakdownTile: {
    flex: 1,
  },
  tileHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
});
