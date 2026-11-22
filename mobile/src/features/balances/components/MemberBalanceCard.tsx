/**
 * MemberBalanceCard component (T-33 / US-10).
 *
 * Renders an individual peer standing item with:
 * - Counterparty name & initials badge.
 * - Directional status badge ("Owes you" / "You owe" / "Settled").
 * - Exact INR amount.
 * - "Record settlement" button (records a repayment made outside the app).
 */

import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { formatPaise } from '@/utils/money';
import type { PeerStanding } from '../types';
import { peerLabel } from '../utils/balanceLabels';

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

  const a11yLabel = peerLabel(standing);

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
          padding: theme.spacing.md,
        },
      ]}
    >
      <View style={[styles.mainRow, { gap: theme.spacing.md }]}>
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
            variant="small"
            style={{ color: statusColor, fontFamily: theme.fontFamily.semibold }}
          >
            {initials}
          </AppText>
        </View>

        {/* Member Details */}
        <View style={[styles.nameBlock, { gap: theme.spacing.xs }]}>
          <AppText variant="bodyStrong" color="textPrimary">
            {standing.name}
          </AppText>
          <View
            style={[
              styles.statusChip,
              {
                backgroundColor: badgeBg,
                borderRadius: theme.radii.sm,
                paddingHorizontal: theme.spacing.sm,
              },
            ]}
          >
            <AppText variant="caption" style={{ color: statusColor }}>
              {isOwed ? 'Owes you' : isOwing ? 'You owe' : 'Settled up'}
            </AppText>
          </View>
        </View>

        {/* Amount */}
        <View style={styles.amountBlock}>
          <AppText variant="money" style={{ color: statusColor }}>
            {isOwed ? '+' : isOwing ? '-' : ''}
            {formatPaise(amountPaise)}
          </AppText>
        </View>
      </View>

      {/* Action Button */}
      {!isSettled && canSettle && onSettlePress ? (
        <View style={[styles.actionRow, { borderTopColor: theme.colors.border, paddingTop: theme.spacing.xs, marginTop: theme.spacing.xs }]}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Record a settlement with ${standing.name}`}
            accessibilityHint="Opens the settle sheet"
            onPress={() => onSettlePress(standing)}
            style={({ pressed }) => [
              styles.settleButton,
              {
                backgroundColor: isOwing ? theme.colors.primary : theme.colors.surfaceMuted,
                borderColor: theme.colors.border,
                borderRadius: theme.radii.sm,
                minHeight: theme.minTouchTarget,
                gap: theme.spacing.sm,
                paddingHorizontal: theme.spacing.md,
                paddingVertical: theme.spacing.sm,
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
              Record settlement
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
  },
  mainRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  avatarCircle: {
    // No size token fits a 40 pt avatar; kept as is (see T-33 report).
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  nameBlock: {
    flex: 1,
  },
  statusChip: {
    alignSelf: 'flex-start',
    // No 1 pt spacing token; kept so the chip height stays the same (see T-33 report).
    paddingVertical: 1,
  },
  amountBlock: {
    alignItems: 'flex-end',
  },
  actionRow: {
    borderTopWidth: 1,
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  settleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
});
