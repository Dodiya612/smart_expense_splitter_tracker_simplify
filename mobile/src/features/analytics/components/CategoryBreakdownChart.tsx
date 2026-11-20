/**
 * Category Breakdown Chart Component (T-43 / US-12).
 *
 * Implements:
 * - Proportional progress bars for categories.
 * - Percentage of total spending.
 * - Count of transactions per category.
 * - Theme-token compliant, accessible labels.
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { formatPaiseToInr } from '@/features/home/utils/dashboardSummary';
import { useTheme } from '@/theme';
import type { CategoryBreakdownItem, SpendingViewMode } from '../types';

export interface CategoryBreakdownChartProps {
  categories: CategoryBreakdownItem[];
  totalPaise: number;
  viewMode: SpendingViewMode;
}

export function CategoryBreakdownChart({
  categories,
  totalPaise,
  viewMode,
}: CategoryBreakdownChartProps) {
  const theme = useTheme();

  if (categories.length === 0) {
    return (
      <AppCard style={styles.card}>
        <AppText variant="bodyStrong" color="textPrimary">
          Spending by Category
        </AppText>
        <View style={styles.emptyBox}>
          <AppText variant="body" color="textSecondary">
            No category expenses recorded in this period.
          </AppText>
        </View>
      </AppCard>
    );
  }

  return (
    <AppCard style={styles.card}>
      <View style={styles.header}>
        <AppText variant="bodyStrong" color="textPrimary">
          Spending by Category
        </AppText>
        <AppText variant="caption" color="textSecondary">
          {categories.length} {categories.length === 1 ? 'category' : 'categories'}
        </AppText>
      </View>

      <View style={styles.list}>
        {categories.map((item, index) => {
          const amount = viewMode === 'share' ? item.sharePaise : item.cashPaidPaise;
          const percentage = totalPaise > 0 ? (amount / totalPaise) * 100 : 0;
          const barWidthPercent = Math.min(Math.max(percentage, 2), 100);

          return (
            <View key={item.categoryId || index} style={styles.itemContainer}>
              <View style={styles.rowTop}>
                <View style={styles.categoryNameCol}>
                  <View
                    style={[
                      styles.dot,
                      {
                        backgroundColor:
                          index === 0
                            ? theme.colors.primary
                            : index === 1
                            ? theme.colors.info.fill
                            : index === 2
                            ? theme.colors.positive.text
                            : theme.colors.textSecondary,
                      },
                    ]}
                  />
                  <AppText variant="body" color="textPrimary" numberOfLines={1}>
                    {item.categoryName}
                  </AppText>
                </View>

                <View style={styles.rowRight}>
                  <AppText variant="bodyStrong" color="textPrimary">
                    {formatPaiseToInr(amount)}
                  </AppText>
                  <AppText variant="caption" color="textSecondary" style={styles.pctText}>
                    ({percentage.toFixed(1)}%)
                  </AppText>
                </View>
              </View>

              {/* Progress bar track */}
              <View
                style={[
                  styles.track,
                  {
                    backgroundColor: theme.colors.surfaceMuted,
                    borderRadius: theme.radii.pill,
                  },
                ]}
              >
                <View
                  style={[
                    styles.fill,
                    {
                      width: `${barWidthPercent}%`,
                      backgroundColor:
                        index === 0
                          ? theme.colors.primary
                          : index === 1
                          ? theme.colors.info.fill
                          : index === 2
                          ? theme.colors.positive.text
                          : theme.colors.textSecondary,
                      borderRadius: theme.radii.pill,
                    },
                  ]}
                />
              </View>

              <AppText variant="caption" color="textSecondary" style={styles.expenseCount}>
                {item.expenseCount} {item.expenseCount === 1 ? 'expense' : 'expenses'}
              </AppText>
            </View>
          );
        })}
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 16,
    gap: 12,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  emptyBox: {
    paddingVertical: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  list: {
    gap: 14,
  },
  itemContainer: {
    gap: 4,
  },
  rowTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  categoryNameCol: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flex: 1,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  rowRight: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 4,
  },
  pctText: {
    fontSize: 11,
  },
  track: {
    height: 6,
    width: '100%',
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
  },
  expenseCount: {
    fontSize: 11,
  },
});
