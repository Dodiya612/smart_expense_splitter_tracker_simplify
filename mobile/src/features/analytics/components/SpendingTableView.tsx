/**
 * Accessible Spending Table View (T-43 / US-12 / NFR-10).
 *
 * Provides an accessible tabular alternative showing the exact same figures as
 * the charts, for screen readers and users who prefer tabular layouts.
 */

import React, { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { formatPaiseToInr } from '@/features/home/utils/dashboardSummary';
import { useTheme } from '@/theme';
import type { CategoryBreakdownItem, SpendingViewMode, TrendBucket } from '../types';

export interface SpendingTableViewProps {
  buckets: TrendBucket[];
  categories: CategoryBreakdownItem[];
  totalPaise: number;
  viewMode: SpendingViewMode;
}

export function SpendingTableView({
  buckets,
  categories,
  totalPaise,
  viewMode,
}: SpendingTableViewProps) {
  const theme = useTheme();
  const [activeTab, setActiveTab] = useState<'trends' | 'categories'>('trends');

  return (
    <AppCard style={styles.card}>
      {/* Table Sub-Tab Switcher */}
      <View style={styles.header}>
        <AppText variant="bodyStrong" color="textPrimary">
          Detailed Table View
        </AppText>

        <View
          style={[
            styles.tabGroup,
            {
              backgroundColor: theme.colors.surfaceMuted,
              borderRadius: theme.radii.pill,
              borderColor: theme.colors.border,
            },
          ]}
          accessibilityRole="tablist"
        >
          <Pressable
            onPress={() => setActiveTab('trends')}
            accessibilityRole="tab"
            accessibilityState={{ selected: activeTab === 'trends' }}
            style={[
              styles.tabBtn,
              activeTab === 'trends' && [
                styles.tabBtnActive,
                theme.shadows.card,
                { backgroundColor: theme.colors.surface, borderRadius: theme.radii.pill },
              ],
            ]}
          >
            <AppText
              variant={activeTab === 'trends' ? 'bodyStrong' : 'caption'}
              color={activeTab === 'trends' ? 'textPrimary' : 'textSecondary'}
              style={styles.tabText}
            >
              Time Trends
            </AppText>
          </Pressable>

          <Pressable
            onPress={() => setActiveTab('categories')}
            accessibilityRole="tab"
            accessibilityState={{ selected: activeTab === 'categories' }}
            style={[
              styles.tabBtn,
              activeTab === 'categories' && [
                styles.tabBtnActive,
                theme.shadows.card,
                { backgroundColor: theme.colors.surface, borderRadius: theme.radii.pill },
              ],
            ]}
          >
            <AppText
              variant={activeTab === 'categories' ? 'bodyStrong' : 'caption'}
              color={activeTab === 'categories' ? 'textPrimary' : 'textSecondary'}
              style={styles.tabText}
            >
              Categories
            </AppText>
          </Pressable>
        </View>
      </View>

      {/* Table Content */}
      {activeTab === 'trends' ? (
        <View style={styles.table} accessibilityLabel="Time trends table">
          <View
            style={[
              styles.tableRow,
              styles.tableHeader,
              { borderBottomColor: theme.colors.border },
            ]}
          >
            <AppText variant="caption" color="textSecondary" style={styles.colPeriod}>
              Period
            </AppText>
            <AppText variant="caption" color="textSecondary" style={styles.colNumber}>
              {viewMode === 'share' ? 'Share' : 'Cash Paid'}
            </AppText>
            <AppText variant="caption" color="textSecondary" style={styles.colNumber}>
              Cumulative
            </AppText>
          </View>

          {buckets.length === 0 ? (
            <View style={styles.emptyRow}>
              <AppText variant="caption" color="textSecondary">
                No trend entries for this period.
              </AppText>
            </View>
          ) : (
            buckets.map((b, idx) => {
              const amount = viewMode === 'share' ? b.sharePaise : b.cashPaidPaise;
              const cumulative = viewMode === 'share' ? b.cumulativeSharePaise : b.cumulativeCashPaidPaise;
              const isEven = idx % 2 === 0;

              return (
                <View
                  key={`${b.bucketStart}-${idx}`}
                  style={[
                    styles.tableRow,
                    {
                      backgroundColor: isEven ? 'transparent' : theme.colors.surfaceMuted,
                      borderBottomColor: theme.colors.border,
                    },
                  ]}
                  accessible={true}
                  accessibilityLabel={`Period: ${b.bucketStart}, Amount: ${formatPaiseToInr(amount)}, Cumulative: ${formatPaiseToInr(cumulative)}`}
                >
                  <AppText variant="caption" color="textPrimary" style={styles.colPeriod}>
                    {b.bucketStart}
                  </AppText>
                  <AppText variant="caption" color="textPrimary" style={styles.colNumber}>
                    {formatPaiseToInr(amount)}
                  </AppText>
                  <AppText variant="caption" color="textSecondary" style={styles.colNumber}>
                    {formatPaiseToInr(cumulative)}
                  </AppText>
                </View>
              );
            })
          )}
        </View>
      ) : (
        <View style={styles.table} accessibilityLabel="Categories table">
          <View
            style={[
              styles.tableRow,
              styles.tableHeader,
              { borderBottomColor: theme.colors.border },
            ]}
          >
            <AppText variant="caption" color="textSecondary" style={styles.colCategory}>
              Category
            </AppText>
            <AppText variant="caption" color="textSecondary" style={styles.colCount}>
              Count
            </AppText>
            <AppText variant="caption" color="textSecondary" style={styles.colNumber}>
              {viewMode === 'share' ? 'Share' : 'Cash Paid'}
            </AppText>
          </View>

          {categories.length === 0 ? (
            <View style={styles.emptyRow}>
              <AppText variant="caption" color="textSecondary">
                No category records for this period.
              </AppText>
            </View>
          ) : (
            categories.map((c, idx) => {
              const amount = viewMode === 'share' ? c.sharePaise : c.cashPaidPaise;
              const isEven = idx % 2 === 0;

              return (
                <View
                  key={c.categoryId || idx}
                  style={[
                    styles.tableRow,
                    {
                      backgroundColor: isEven ? 'transparent' : theme.colors.surfaceMuted,
                      borderBottomColor: theme.colors.border,
                    },
                  ]}
                  accessible={true}
                  accessibilityLabel={`Category: ${c.categoryName}, Count: ${c.expenseCount}, Amount: ${formatPaiseToInr(amount)}`}
                >
                  <AppText variant="caption" color="textPrimary" style={styles.colCategory} numberOfLines={1}>
                    {c.categoryName}
                  </AppText>
                  <AppText variant="caption" color="textSecondary" style={styles.colCount}>
                    {c.expenseCount}
                  </AppText>
                  <AppText variant="caption" color="textPrimary" style={styles.colNumber}>
                    {formatPaiseToInr(amount)}
                  </AppText>
                </View>
              );
            })
          )}
        </View>
      )}

      {/* Table Footer Total */}
      <View style={[styles.footerRow, { borderTopColor: theme.colors.border }]}>
        <AppText variant="bodyStrong" color="textPrimary">
          Total
        </AppText>
        <AppText variant="bodyStrong" color="textPrimary">
          {formatPaiseToInr(totalPaise)}
        </AppText>
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
    gap: 8,
  },
  tabGroup: {
    flexDirection: 'row',
    padding: 2,
    borderWidth: 1,
  },
  tabBtn: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabBtnActive: {},
  tabText: {
    fontSize: 11,
  },
  table: {
    borderWidth: 1,
    borderColor: 'transparent',
  },
  tableRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 8,
    borderBottomWidth: 1,
  },
  tableHeader: {
    borderBottomWidth: 1.5,
  },
  colPeriod: {
    flex: 2,
  },
  colCategory: {
    flex: 2,
  },
  colCount: {
    flex: 1,
    textAlign: 'center',
  },
  colNumber: {
    flex: 2,
    textAlign: 'right',
  },
  emptyRow: {
    paddingVertical: 16,
    alignItems: 'center',
  },
  footerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: 8,
    borderTopWidth: 1,
  },
});
