/**
 * BudgetCard Component (T-49 / US-25).
 *
 * Displays:
 * - Scope (Overall or Category name + icon)
 * - Period (Weekly / Monthly)
 * - Spent, Remaining, Over-by amount
 * - Percentage used
 * - Horizontal linear progress bar
 * - Status labels (Under budget, Near budget limit, Budget exceeded)
 * - Edit limit and Delete actions
 * - 100% accessible with screen-reader friendly textual labels
 */

import React from 'react';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { formatPaiseToInr } from '@/features/home/utils/dashboardSummary';
import { useTheme } from '@/theme';
import type { Budget } from '../types';
import { getCategoryMeta } from '../utils/categories';
import { BudgetProgressBar } from './BudgetProgressBar';

export interface BudgetCardProps {
  budget: Budget;
  onEdit?: (budget: Budget) => void;
  onDelete?: (budget: Budget) => void;
  testID?: string;
}

export function BudgetCard({ budget, onEdit, onDelete, testID = 'budget-card' }: BudgetCardProps) {
  const theme = useTheme();

  const { period, categoryId, limitPaise, progress } = budget;
  const { spentPaise, remainingPaise, percentUsed, status } = progress;

  const categoryMeta = getCategoryMeta(categoryId);
  const title = categoryMeta ? categoryMeta.name : 'Overall Budget';
  const iconName = categoryMeta ? categoryMeta.icon : 'wallet-outline';
  const periodLabel = period === 'weekly' ? 'Weekly' : 'Monthly';

  // Format monetary amounts
  const formattedLimit = formatPaiseToInr(limitPaise);
  const formattedSpent = formatPaiseToInr(spentPaise);
  const isOver = status === 'exceeded' || remainingPaise < 0;
  const formattedRemaining = isOver
    ? `${formatPaiseToInr(Math.abs(remainingPaise))} over budget`
    : `${formatPaiseToInr(remainingPaise)} remaining`;

  // Status badge config
  const getStatusBadge = () => {
    switch (status) {
      case 'exceeded':
        return {
          text: 'Budget exceeded',
          bg: theme.colors.negative.soft,
          color: theme.colors.negative.text,
          border: theme.colors.negative.text,
        };
      case 'warning':
        return {
          text: 'Near budget limit',
          bg: theme.colors.warning.soft,
          color: theme.colors.warning.text,
          border: theme.colors.warning.text,
        };
      case 'under':
      default:
        return {
          text: 'Under budget',
          bg: theme.colors.positive.soft,
          color: theme.colors.positive.text,
          border: theme.colors.positive.text,
        };
    }
  };

  const badge = getStatusBadge();

  // Screen reader accessible label
  const a11ySummary = `${periodLabel} ${title}: limit ${formattedLimit}, spent ${formattedSpent}, ${percentUsed} percent used, ${formattedRemaining}. Status: ${badge.text}.`;

  return (
    <AppCard
      accessibilityRole="summary"
      accessibilityLabel={a11ySummary}
      style={[styles.card, { gap: theme.spacing.md }]}
    >
      {/* ── Header ────────────────────────────────────────────── */}
      <View style={styles.headerRow}>
        <View style={[styles.titleGroup, { gap: theme.spacing.sm }]}>
          <View
            style={[
              styles.iconWrapper,
              {
                backgroundColor: theme.colors.surfaceMuted,
                borderRadius: theme.radii.md,
              },
            ]}
          >
            <Ionicons name={iconName as any} size={20} color={theme.colors.primary} />
          </View>
          <View>
            <AppText variant="bodyStrong" color="textPrimary">
              {title}
            </AppText>
            <AppText variant="caption" color="textSecondary">
              {periodLabel} · Limit {formattedLimit}
            </AppText>
          </View>
        </View>

        {/* Action buttons (Edit & Delete) */}
        <View style={[styles.actionGroup, { gap: theme.spacing.xs }]}>
          {onEdit && (
            <TouchableOpacity
              testID={`${testID}-edit-btn`}
              accessibilityRole="button"
              accessibilityLabel={`Edit limit for ${title}`}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              onPress={() => onEdit(budget)}
              style={[
                styles.actionBtn,
                { minHeight: 44, minWidth: 44, justifyContent: 'center', alignItems: 'center' },
              ]}
            >
              <Ionicons name="pencil-outline" size={18} color={theme.colors.textSecondary} />
            </TouchableOpacity>
          )}
          {onDelete && (
            <TouchableOpacity
              testID={`${testID}-delete-btn`}
              accessibilityRole="button"
              accessibilityLabel={`Delete ${title}`}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              onPress={() => onDelete(budget)}
              style={[
                styles.actionBtn,
                { minHeight: 44, minWidth: 44, justifyContent: 'center', alignItems: 'center' },
              ]}
            >
              <Ionicons name="trash-outline" size={18} color={theme.colors.negative.text} />
            </TouchableOpacity>
          )}
        </View>
      </View>

      {/* ── Progress Bar ───────────────────────────────────────── */}
      <View style={{ gap: theme.spacing.xs }}>
        <BudgetProgressBar
          percentUsed={percentUsed}
          status={status}
          height={8}
          testID={`${testID}-progress`}
        />
      </View>

      {/* ── Spending Figures & Status ─────────────────────────── */}
      <View style={styles.footerRow}>
        <View>
          <AppText variant="caption" color="textSecondary">
            Spent
          </AppText>
          <AppText variant="bodyStrong" color="textPrimary">
            {formattedSpent} ({percentUsed}%)
          </AppText>
        </View>

        <View style={styles.rightFigure}>
          <AppText variant="caption" color="textSecondary">
            {isOver ? 'Over by' : 'Remaining'}
          </AppText>
          <AppText
            variant="bodyStrong"
            color={isOver ? 'negative' : 'textPrimary'}
          >
            {formattedRemaining}
          </AppText>
        </View>
      </View>

      {/* ── Textual Status Badge (Never Color Alone) ──────────── */}
      <View style={styles.badgeRow}>
        <View
          style={[
            styles.badge,
            {
              backgroundColor: badge.bg,
              borderColor: badge.border,
              borderRadius: theme.radii.pill,
            },
          ]}
        >
          <AppText
            variant="caption"
            style={[styles.badgeText, { color: badge.color }]}
          >
            {badge.text}
          </AppText>
        </View>
        <AppText variant="caption" color="textSecondary">
          {progress.periodStart} to {progress.periodEnd}
        </AppText>
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  card: {
    width: '100%',
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  titleGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  iconWrapper: {
    width: 36,
    height: 36,
    justifyContent: 'center',
    alignItems: 'center',
  },
  actionGroup: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  actionBtn: {
    padding: 6,
  },
  footerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  rightFigure: {
    alignItems: 'flex-end',
  },
  badgeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: 4,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderWidth: 1,
  },
  badgeText: {
    fontWeight: '600',
  },
});
