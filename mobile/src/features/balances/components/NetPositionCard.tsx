/**
 * NetPositionCard component (T-33 / US-10).
 *
 * Displays:
 * - Net balance standing across the group.
 * - Clear breakdowns of "You are owed" (+ green) and "You owe" (- red).
 * - Full accessible labeling and INR currency formatting.
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';

export interface NetPositionCardProps {
  netBalancePaise: number;
  youAreOwedPaise: number;
  youOwePaise: number;
  currency?: string;
}

export function formatInr(paise: number): string {
  const absPaise = Math.abs(paise);
  const rupees = absPaise / 100;
  return `₹${rupees.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
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
    : `Net standing: you are owed ${formatInr(youAreOwedPaise)}, and you owe ${formatInr(youOwePaise)}.`;

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
        <View style={styles.titleWithIcon}>
          <Ionicons
            name="wallet-outline"
            size={20}
            color={theme.colors.primary}
          />
          <AppText variant="bodyStrong" color="textPrimary">
            Your Balance in Group
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
            {isNetCreditor
              ? 'You are owed'
              : isNetDebtor
                ? 'You owe'
                : 'Settled up'}
          </AppText>
        </View>
      </View>

      {/* ── Net Big Number ────────────────────────────────────── */}
      <View style={styles.netAmountBlock}>
        <AppText
          style={[
            styles.netAmountText,
            {
              color: netColor,
              fontFamily: theme.fontFamily.bold,
            },
          ]}
          accessibilityLabel={`Net position ${netPrefix}${formatInr(netBalancePaise)}`}
        >
          {netPrefix}
          {formatInr(netBalancePaise)}
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
          <View style={styles.tileHeader}>
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
            variant="bodyStrong"
            style={{ color: theme.colors.positive.text, marginTop: 2 }}
          >
            +{formatInr(youAreOwedPaise)}
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
          <View style={styles.tileHeader}>
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
            variant="bodyStrong"
            style={{ color: theme.colors.negative.text, marginTop: 2 }}
          >
            -{formatInr(youOwePaise)}
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
    gap: 8,
  },
  statusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderWidth: 1,
  },
  netAmountBlock: {
    marginVertical: 4,
  },
  netAmountText: {
    fontSize: 30,
    lineHeight: 38,
    fontVariant: ['tabular-nums'],
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
    gap: 4,
  },
});
