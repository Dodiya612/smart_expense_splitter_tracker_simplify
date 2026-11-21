/**
 * BudgetRecommendationCard Component (T-55 / US-25).
 *
 * Advisory AI Smart Budget Goal Card:
 * - Transparent 3-month median calculation display
 * - Spike-trimming amounts and savings level deduction (0%, 5%, 10%)
 * - AI explanation from Groq or deterministic fallback with clear provenance badge
 * - Insufficient history advisory notice
 * - Interactive Apply action that prefills budget modal for user confirmation
 */

import React from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { formatPaiseToInr } from '@/features/home/utils/dashboardSummary';
import { useTheme } from '@/theme';
import type {
  BudgetRecommendation,
  HistoricalMonthSpend,
  SavingsLevelPercent,
} from '../services/budgetsApi';
import { DEFAULT_BUDGET_CATEGORIES, getCategoryMeta } from '../utils/categories';

export interface BudgetRecommendationCardProps {
  recommendation: BudgetRecommendation | null;
  isLoading: boolean;
  error: string | null;
  selectedSavingsLevel: SavingsLevelPercent;
  onChangeSavingsLevel: (level: SavingsLevelPercent) => void;
  selectedCategoryId: string | null;
  onChangeCategory: (categoryId: string | null) => void;
  onRetry: () => void;
  onApply: (recommendation: BudgetRecommendation) => void;
}

export function BudgetRecommendationCard({
  recommendation,
  isLoading,
  error,
  selectedSavingsLevel,
  onChangeSavingsLevel,
  selectedCategoryId,
  onChangeCategory,
  onRetry,
  onApply,
}: BudgetRecommendationCardProps) {
  const theme = useTheme();

  const isAiSource = recommendation?.source === 'ai';
  const totalSpikesPaise =
    recommendation?.historicalMonths.reduce((sum, m) => sum + m.spikePaise, 0) ?? 0;

  const categoryLabel = selectedCategoryId
    ? getCategoryMeta(selectedCategoryId)?.name ?? 'Category'
    : 'Overall';

  return (
    <AppCard style={[styles.card, { borderColor: theme.colors.border, gap: theme.spacing.sm }]}>
      {/* ── Card Header ────────────────────────────────────────── */}
      <View style={styles.headerRow}>
        <View style={styles.headerTitleGroup}>
          <Ionicons name="sparkles" size={20} color={theme.colors.info.text} />
          <AppText variant="heading" color="textPrimary">
            AI Smart Budget Goal
          </AppText>
        </View>

        {recommendation && (
          <View
            style={[
              styles.badge,
              {
                backgroundColor: isAiSource
                  ? theme.colors.info.soft
                  : theme.colors.surfaceMuted,
                borderRadius: theme.radii.pill,
              },
            ]}
          >
            <AppText
              variant="small"
              color={isAiSource ? 'info' : 'textSecondary'}
            >
              {isAiSource ? '🤖 AI Insight' : '📐 Rule-Based'}
            </AppText>
          </View>
        )}
      </View>

      {/* ── Category / Scope Selector ──────────────────── */}
      <View style={[styles.sectionGap, { gap: theme.spacing.xs }]}>
        <AppText variant="small" color="textSecondary">
          Budget Scope:
        </AppText>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={[styles.categoryScroll, { gap: theme.spacing.xs }]}
        >
          <TouchableOpacity
            testID="rec-scope-overall"
            accessibilityRole="tab"
            accessibilityState={{ selected: selectedCategoryId === null }}
            accessibilityLabel="Scope: Overall budget"
            onPress={() => onChangeCategory(null)}
            style={[
              styles.scopeChip,
              {
                backgroundColor:
                  selectedCategoryId === null
                    ? theme.colors.surfaceMuted
                    : theme.colors.surface,
                borderColor:
                  selectedCategoryId === null
                    ? theme.colors.primary
                    : theme.colors.border,
                borderRadius: theme.radii.pill,
              },
            ]}
          >
            <AppText
              variant="small"
              color={selectedCategoryId === null ? 'textPrimary' : 'textSecondary'}
            >
              Overall
            </AppText>
          </TouchableOpacity>

          {DEFAULT_BUDGET_CATEGORIES.map((cat) => {
            const isSelected = selectedCategoryId === cat.id;
            return (
              <TouchableOpacity
                key={cat.id}
                testID={`rec-scope-cat-${cat.formId}`}
                accessibilityRole="tab"
                accessibilityState={{ selected: isSelected }}
                accessibilityLabel={`Scope: ${cat.name}`}
                onPress={() => onChangeCategory(cat.id)}
                style={[
                  styles.scopeChip,
                  {
                    backgroundColor: isSelected
                      ? theme.colors.surfaceMuted
                      : theme.colors.surface,
                    borderColor: isSelected
                      ? theme.colors.primary
                      : theme.colors.border,
                    borderRadius: theme.radii.pill,
                  },
                ]}
              >
                <AppText
                  variant="small"
                  color={isSelected ? 'textPrimary' : 'textSecondary'}
                >
                  {cat.name}
                </AppText>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      </View>

      {/* ── Savings Level Selector ─────────────────────── */}
      <View style={[styles.sectionGap, { gap: theme.spacing.xs }]}>
        <AppText variant="small" color="textSecondary">
          Target Savings Rate:
        </AppText>
        <View style={[styles.savingsLevelRow, { gap: theme.spacing.xs }]}>
          {([0, 5, 10] as const).map((level) => {
            const isSelected = selectedSavingsLevel === level;
            const levelLabel =
              level === 0 ? '0% (Maintain)' : level === 5 ? '5% (Moderate)' : '10% (Target)';
            return (
              <TouchableOpacity
                key={level}
                testID={`savings-level-${level}`}
                accessibilityRole="button"
                accessibilityState={{ selected: isSelected }}
                accessibilityLabel={`Savings level ${levelLabel}`}
                onPress={() => onChangeSavingsLevel(level)}
                style={[
                  styles.savingsLevelChip,
                  {
                    backgroundColor: isSelected
                      ? theme.colors.surfaceMuted
                      : theme.colors.surface,
                    borderColor: isSelected
                      ? theme.colors.primary
                      : theme.colors.border,
                    borderRadius: theme.radii.sm,
                  },
                ]}
              >
                <AppText
                  variant="small"
                  color={isSelected ? 'textPrimary' : 'textSecondary'}
                >
                  {levelLabel}
                </AppText>
              </TouchableOpacity>
            );
          })}
        </View>
      </View>

      {/* ── Loading State ──────────────────────────────────────── */}
      {isLoading && (
        <View style={[styles.loadingBox, { padding: theme.spacing.md, gap: theme.spacing.xs }]}>
          <ActivityIndicator size="small" color={theme.colors.info.text} />
          <AppText variant="caption" color="textSecondary">
            Analyzing spending history and generating recommendation...
          </AppText>
        </View>
      )}

      {/* ── Error State ────────────────────────────────────────── */}
      {!isLoading && error && (
        <View
          style={[
            styles.errorBox,
            {
              backgroundColor: theme.colors.negative.soft,
              borderColor: theme.colors.negative.text,
              borderRadius: theme.radii.md,
              padding: theme.spacing.sm,
              gap: theme.spacing.xs,
            },
          ]}
        >
          <View style={styles.errorHeader}>
            <Ionicons name="alert-circle-outline" size={18} color={theme.colors.negative.text} />
            <AppText variant="small" color="negative" style={styles.flex1}>
              {error}
            </AppText>
          </View>
          <Button
            label="Retry Recommendation"
            variant="outline"
            onPress={onRetry}
            accessibilityLabel="Retry fetching budget recommendation"
          />
        </View>
      )}

      {/* ── Main Recommendation Details ───────────────────────── */}
      {!isLoading && !error && recommendation && (
        <>
          {/* Insufficient History Notice */}
          {!recommendation.hasSufficientHistory && (
            <View
              style={[
                styles.noticeBox,
                {
                  backgroundColor: theme.colors.warning.soft,
                  borderColor: theme.colors.warning.text,
                  borderRadius: theme.radii.sm,
                  padding: theme.spacing.sm,
                  gap: theme.spacing.xs,
                },
              ]}
            >
              <View style={styles.noticeHeader}>
                <Ionicons
                  name="information-circle-outline"
                  size={18}
                  color={theme.colors.warning.text}
                />
                <AppText variant="small" color="warning" style={styles.flex1}>
                  Limited History Notice
                </AppText>
              </View>
              <AppText variant="caption" color="warning">
                Less than 3 completed months of history are recorded. Recommendation is calculated
                using available data or baseline estimates.
              </AppText>
            </View>
          )}

          {/* Recommended Amount Highlight */}
          <View
            style={[
              styles.amountContainer,
              {
                backgroundColor: theme.colors.surfaceMuted,
                borderRadius: theme.radii.md,
                padding: theme.spacing.md,
              },
            ]}
          >
            <AppText variant="small" color="textSecondary">
              Recommended {categoryLabel} Monthly Limit
            </AppText>
            <View style={styles.amountRow}>
              <AppText variant="title" color="textPrimary">
                {formatPaiseToInr(recommendation.recommendedLimitPaise)}
              </AppText>
              <AppText variant="caption" color="textSecondary">
                / month
              </AppText>
            </View>
          </View>

          {/* Explanation Quote */}
          {recommendation.explanation ? (
            <View
              style={[
                styles.explanationBox,
                {
                  backgroundColor: theme.colors.info.soft,
                  borderRadius: theme.radii.sm,
                  padding: theme.spacing.sm,
                  borderColor: theme.colors.info.fill,
                },
              ]}
            >
              <AppText variant="body" color="info">
                "{recommendation.explanation}"
              </AppText>
            </View>
          ) : null}

          {/* Calculation Transparency Breakdown */}
          <View
            style={[
              styles.breakdownContainer,
              {
                borderColor: theme.colors.border,
                borderRadius: theme.radii.sm,
                padding: theme.spacing.sm,
                gap: theme.spacing.xs,
              },
            ]}
          >
            <AppText variant="bodyStrong" color="textPrimary">
              Calculation Breakdown
            </AppText>

            <View style={styles.breakdownRow}>
              <AppText variant="caption" color="textSecondary">
                Median Monthly Spending:
              </AppText>
              <AppText variant="bodyStrong" color="textPrimary">
                {formatPaiseToInr(recommendation.rawMedianPaise)}
              </AppText>
            </View>

            <View style={styles.breakdownRow}>
              <AppText variant="caption" color="textSecondary">
                Savings Target ({recommendation.savingsLevelPercent}%):
              </AppText>
              <AppText variant="bodyStrong" color="positive">
                - {formatPaiseToInr(recommendation.savingsPaise)}
              </AppText>
            </View>

            {totalSpikesPaise > 0 && (
              <View style={styles.breakdownRow}>
                <AppText variant="caption" color="textSecondary">
                  Trimmed One-Off Spikes:
                </AppText>
                <AppText variant="bodyStrong" color="warning">
                  - {formatPaiseToInr(totalSpikesPaise)}
                </AppText>
              </View>
            )}

            {/* Historical Months Table */}
            {recommendation.historicalMonths.length > 0 && (
              <View
                style={[
                  styles.historySection,
                  {
                    borderTopColor: theme.colors.border,
                    gap: 4,
                    marginTop: theme.spacing.xs,
                  },
                ]}
              >
                <AppText variant="small" color="textSecondary">
                  Recent Months Considered:
                </AppText>
                {recommendation.historicalMonths.map((m: HistoricalMonthSpend) => (
                  <View key={m.month} style={styles.historyRow}>
                    <AppText variant="caption" color="textPrimary">
                      {m.month}
                    </AppText>
                    <View style={styles.historyAmounts}>
                      <AppText variant="caption" color="textSecondary">
                        Spent {formatPaiseToInr(m.spentPaise)}
                      </AppText>
                      {m.spikePaise > 0 && (
                        <AppText variant="caption" color="warning">
                          (trimmed {formatPaiseToInr(m.spikePaise)})
                        </AppText>
                      )}
                      <AppText variant="bodyStrong" color="textPrimary">
                        = Net {formatPaiseToInr(m.netPaise)}
                      </AppText>
                    </View>
                  </View>
                ))}
              </View>
            )}
          </View>

          {/* Apply Recommendation Action */}
          <View style={[styles.actionSection, { gap: theme.spacing.xs, marginTop: theme.spacing.xs }]}>
            <Button
              testID="btn-apply-recommendation"
              label={`Apply ${formatPaiseToInr(recommendation.recommendedLimitPaise)} Goal`}
              variant="primary"
              fullWidth
              onPress={() => onApply(recommendation)}
              accessibilityLabel={`Apply recommended limit of ${formatPaiseToInr(
                recommendation.recommendedLimitPaise
              )} to budget form`}
            />
            <AppText variant="caption" color="textSecondary" style={styles.centerText}>
              Opens budget form with recommended amount prefilled for your review and confirmation.
            </AppText>
          </View>
        </>
      )}
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
  headerTitleGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  sectionGap: {
    marginTop: 2,
  },
  categoryScroll: {
    paddingVertical: 2,
  },
  scopeChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderWidth: 1,
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
  },
  savingsLevelRow: {
    flexDirection: 'row',
  },
  savingsLevelChip: {
    flex: 1,
    paddingVertical: 10,
    borderWidth: 1,
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingBox: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  errorBox: {
    borderWidth: 1,
  },
  errorHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  noticeBox: {
    borderWidth: 1,
  },
  noticeHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  amountContainer: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  amountRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 4,
    marginTop: 2,
  },
  explanationBox: {
    borderLeftWidth: 3,
  },
  breakdownContainer: {
    borderWidth: 1,
  },
  breakdownRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  historySection: {
    borderTopWidth: 1,
    paddingTop: 6,
  },
  historyRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  historyAmounts: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  actionSection: {
    alignItems: 'stretch',
  },
  centerText: {
    textAlign: 'center',
  },
  flex1: {
    flex: 1,
  },
});
