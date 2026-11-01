import React from 'react';
import { DimensionValue, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { BudgetSummary } from '../types';
import { formatPaiseToInr } from '../utils/dashboardSummary';

export interface BudgetPreviewCardProps {
  budget: BudgetSummary;
}

export function BudgetPreviewCard({ budget }: BudgetPreviewCardProps) {
  const theme = useTheme();

  const hasLimit = budget.monthlyLimitPaise > 0;
  const isOverBudget = hasLimit && budget.remainingPaise < 0;
  const safePercentage = Math.max(0, Math.min(100, isNaN(budget.percentageSpent) ? 0 : budget.percentageSpent));
  const progressWidth: DimensionValue = `${safePercentage}%`;

  const getProgressColor = () => {
    if (isOverBudget) return theme.colors.negative.fill;
    if (safePercentage >= 80) return theme.colors.warning.fill;
    return theme.colors.info.fill;
  };

  const formattedLimit = formatPaiseToInr(budget.monthlyLimitPaise);
  const formattedRemaining = isOverBudget
    ? `${formatPaiseToInr(Math.abs(budget.remainingPaise))} over budget`
    : `+${formatPaiseToInr(budget.remainingPaise)} remaining`;

  const a11yLabel = hasLimit
    ? `Monthly budget preview. Limit ${formattedLimit}, spent ${safePercentage} percent, ${formattedRemaining}.`
    : 'Monthly budget preview. No budget limit configured.';

  return (
    <AppCard
      accessibilityRole="summary"
      accessibilityLabel={a11yLabel}
      style={{ gap: theme.spacing.sm }}
    >
      {/* ── Header ────────────────────────────────────────────── */}
      <View style={styles.cardHeader}>
        <View style={[styles.titleRow, { gap: theme.spacing.xs }]}>
          <Ionicons name="wallet-outline" size={18} color={theme.colors.primary} />
          <AppText variant="bodyStrong" color="textPrimary">
            Monthly budget
          </AppText>
        </View>
      </View>

      {/* ── Progress Bar ───────────────────────────────────────── */}
      <View
        style={[
          styles.progressBarTrack,
          {
            backgroundColor: theme.colors.surfaceMuted,
            borderRadius: theme.radii.pill,
          },
        ]}
      >
        <View
          style={[
            styles.progressBarFill,
            {
              backgroundColor: getProgressColor(),
              borderRadius: theme.radii.pill,
              width: progressWidth,
            },
          ]}
        />
      </View>

      {/* ── Metrics / Footer ───────────────────────────────────── */}
      {hasLimit ? (
        <View style={styles.cardFooter}>
          <AppText variant="caption" color="textSecondary">
            {`Limit: ${formattedLimit} (${safePercentage}%)`}
          </AppText>
          <AppText
            variant="caption"
            color={isOverBudget ? 'negative' : 'positive'}
            numberOfLines={1}
          >
            {formattedRemaining}
          </AppText>
        </View>
      ) : (
        <View style={styles.cardFooter}>
          <AppText variant="caption" color="textSecondary">
            No budget limit set for this month
          </AppText>
        </View>
      )}
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
  },
  progressBarTrack: {
    width: '100%',
    height: 8,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: 8,
  },
  cardFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 4,
  },
});
