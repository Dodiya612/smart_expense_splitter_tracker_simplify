/**
 * MemberBalanceCard component (T-33 / US-10).
 *
 * Renders an individual peer standing item with:
 * - Counterparty name & initials badge.
 * - Directional status badge ("Owes you" / "You owe" / "Settled").
 * - Exact INR amount.
 * - Direct "Settle Up" action trigger button.
 */

import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { PeerStanding } from '../hooks/useGroupBalances';
import { formatInr } from './NetPositionCard';

export interface MemberBalanceCardProps {
  standing: PeerStanding;
  onSettlePress?: (standing: PeerStanding) => void;
  canSettle?: boolean;
}

export function MemberBalanceCard({
  standing,
  onSettlePress,
  canSettle = true,
}: MemberBalanceCardProps) {
  const theme = useTheme();

  const isOwed = standing.status === 'owes_you';
  const isOwing = standing.status === 'you_owe';
  const isSettled = standing.status === 'settled';

  const amountPaise = Math.abs(standing.netAmountPaise);

  const initials = standing.name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || 'M';

  const statusColor = isOwed
    ? theme.colors.positive.text
    : isOwing
      ? theme.colors.negative.text
      : theme.colors.textSecondary;

  const badgeBg = isOwed
    ? theme.colors.positive.soft
    : isOwing
      ? theme.colors.negative.soft
      : theme.colors.surfaceMuted;

  const a11yLabel = isOwed
    ? `${standing.name} owes you ${formatInr(amountPaise)}`
    : isOwing
      ? `You owe ${standing.name} ${formatInr(amountPaise)}`
      : `${standing.name} is settled up`;

  return (
    <AppCard
      accessibilityRole="summary"
      accessibilityLabel={a11yLabel}
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          gap: theme.spacing.sm,
        },
      ]}
    >
      <View style={styles.mainRow}>
        {/* Member Avatar / Initials */}
        <View
          style={[
            styles.avatarCircle,
            {
              backgroundColor: isOwed
                ? theme.colors.positive.soft
                : isOwing
                  ? theme.colors.negative.soft
                  : theme.colors.surfaceMuted,
              borderRadius: theme.radii.pill,
            },
          ]}
        >
          <AppText
            variant="bodyStrong"
            style={{ color: statusColor, fontSize: 14 }}
          >
            {initials}
          </AppText>
        </View>

        {/* Member Details */}
        <View style={styles.nameBlock}>
          <AppText variant="bodyStrong" color="textPrimary">
            {standing.name}
          </AppText>
          <View
            style={[
              styles.statusChip,
              {
                backgroundColor: badgeBg,
                borderRadius: theme.radii.sm,
              },
            ]}
          >
            <AppText variant="caption" style={{ color: statusColor, fontSize: 11 }}>
              {isOwed ? 'Owes you' : isOwing ? 'You owe' : 'Settled up'}
            </AppText>
          </View>
        </View>

        {/* Amount */}
        <View style={styles.amountBlock}>
          <AppText
            variant="bodyStrong"
            style={[styles.amountText, { color: statusColor }]}
          >
            {isOwed ? '+' : isOwing ? '-' : ''}
            {formatInr(amountPaise)}
          </AppText>
        </View>
      </View>

      {/* Action Button */}
      {!isSettled && canSettle && onSettlePress ? (
        <View style={[styles.actionRow, { borderTopColor: theme.colors.border, paddingTop: theme.spacing.xs }]}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Settle balance with ${standing.name}`}
            accessibilityHint="Opens settlement dialog"
            onPress={() => onSettlePress(standing)}
            style={({ pressed }) => [
              styles.settleButton,
              {
                backgroundColor: isOwing ? theme.colors.primary : theme.colors.surfaceMuted,
                borderColor: theme.colors.border,
                borderRadius: theme.radii.sm,
                minHeight: theme.minTouchTarget,
                opacity: pressed ? 0.75 : 1,
              },
            ]}
          >
            <Ionicons
              name={isOwing ? 'card-outline' : 'receipt-outline'}
              size={16}
              color={isOwing ? theme.colors.textOnPrimary : theme.colors.textPrimary}
            />
            <AppText
              variant="caption"
              style={{
                color: isOwing ? theme.colors.textOnPrimary : theme.colors.textPrimary,
                fontFamily: theme.fontFamily.semibold,
              }}
            >
              {isOwing ? 'Pay / Settle Up' : 'Record Payment'}
            </AppText>
          </Pressable>
        </View>
      ) : null}
    </AppCard>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    padding: 12,
  },
  mainRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  avatarCircle: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  nameBlock: {
    flex: 1,
    gap: 4,
  },
  statusChip: {
    alignSelf: 'flex-start',
    paddingHorizontal: 6,
    paddingVertical: 1,
  },
  amountBlock: {
    alignItems: 'flex-end',
  },
  amountText: {
    fontSize: 16,
    fontVariant: ['tabular-nums'],
  },
  actionRow: {
    borderTopWidth: 1,
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginTop: 4,
  },
  settleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderWidth: 1,
  },
});
