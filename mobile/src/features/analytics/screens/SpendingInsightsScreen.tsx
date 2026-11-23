/**
 * SpendingInsightsScreen (T-43 / US-12).
 *
 * Implements:
 * - Spending trend chart (by day, week, month).
 * - Category spending breakdown chart.
 * - Date range filter (1M, 3M, 6M, 1Y).
 * - Share / Cash Paid switch.
 * - Accessible table view showing the same underlying figures.
 * - Loading, empty, error (with retry), and success states.
 * - Auto-refreshes when screen becomes focused (after an expense edit).
 */

import React, { useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import { CategoryBreakdownChart } from '../components/CategoryBreakdownChart';
import { DateRangeSelector } from '../components/DateRangeSelector';
import { ShareCashToggle } from '../components/ShareCashToggle';
import { SpendingTableView } from '../components/SpendingTableView';
import { SpendingTrendChart } from '../components/SpendingTrendChart';
import { useSpendingAnalytics } from '../hooks/useSpendingAnalytics';

export interface SpendingInsightsScreenProps {
  groupId?: string;
}

export function SpendingInsightsScreen({ groupId }: SpendingInsightsScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  const {
    summary,
    trends,
    categories,
    isLoading,
    isRefreshing,
    error,
    viewMode,
    setViewMode,
    preset,
    setPreset,
    granularity,
    setGranularity,
    fromDate,
    toDate,
    setCustomRange,
    refresh,
    retry,
  } = useSpendingAnalytics({ groupId });

  const [showTableView, setShowTableView] = useState<boolean>(false);

  // Active amounts
  const totalAmount = summary
    ? viewMode === 'share'
      ? summary.sharePaise
      : summary.cashPaidPaise
    : 0;

  // Loading state (initial)
  if (isLoading && !summary) {
    return (
      <View
        style={[styles.centerContainer, { backgroundColor: theme.colors.background }]}
        accessibilityRole="alert"
        accessibilityLabel="Loading spending insights"
      >
        <ActivityIndicator size="large" color={theme.colors.primary} />
        <AppText variant="body" color="textSecondary" style={{ marginTop: theme.spacing.md }}>
          Calculating spending insights...
        </AppText>
      </View>
    );
  }

  // Error state (initial)
  if (error && !summary) {
    return (
      <View
        style={[
          styles.centerContainer,
          { backgroundColor: theme.colors.background, padding: theme.spacing.xl },
        ]}
        accessibilityRole="alert"
      >
        <Ionicons name="alert-circle-outline" size={48} color={theme.colors.negative.text} />
        <AppText variant="heading" color="textPrimary" style={{ marginTop: theme.spacing.md, textAlign: 'center' }}>
          Could not load analytics
        </AppText>
        <AppText variant="body" color="textSecondary" style={{ marginTop: theme.spacing.xs, textAlign: 'center' }}>
          {error.message || 'Unable to fetch spending figures.'}
        </AppText>
        <View style={{ marginTop: theme.spacing.lg, width: '100%' }}>
          <Button label="Try Again" variant="primary" fullWidth onPress={() => void retry()} />
        </View>
      </View>
    );
  }

  const isEmpty = summary ? summary.expenseCount === 0 : false;

  return (
    <ScrollView
      style={[styles.root, { backgroundColor: theme.colors.background }]}
      contentContainerStyle={[
        styles.scrollContent,
        {
          paddingTop: Math.max(insets.top, theme.spacing.md),
          paddingBottom: Math.max(insets.bottom, theme.spacing.md) + 90, // safe area for tab bar
        },
      ]}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={() => void refresh()}
          tintColor={theme.colors.primary}
        />
      }
    >
      {/* Top Header */}
      <View style={styles.header}>
        <View>
          <AppText variant="title" color="textPrimary">
            Spending Insights
          </AppText>
          <AppText variant="body" color="textSecondary" style={styles.subtitle}>
            Total spending and breakdown over time
          </AppText>
        </View>
      </View>

      {/* Share vs Cash Paid Switch */}
      <ShareCashToggle
        mode={viewMode}
        onChange={setViewMode}
        disabled={isLoading || isRefreshing}
      />

      {/* Date Range Selector */}
      <DateRangeSelector
        preset={preset}
        onSelectPreset={setPreset}
        onSelectCustomRange={setCustomRange}
        fromDate={fromDate}
        toDate={toDate}
        disabled={isLoading || isRefreshing}
      />

      {/* Subsequent filter error banner */}
      {error && summary ? (
        <AppCard
          style={[
            styles.inlineErrorCard,
            {
              backgroundColor: theme.colors.negative.soft,
              borderColor: theme.colors.negative.text,
            },
          ]}
          accessibilityRole="alert"
        >
          <View style={styles.inlineErrorRow}>
            <Ionicons name="alert-circle" size={20} color={theme.colors.negative.text} />
            <View style={styles.inlineErrorTextCol}>
              <AppText variant="bodyStrong" color="negative">
                Could not refresh spending data
              </AppText>
              <AppText variant="caption" color="textSecondary" style={{ marginTop: 2 }}>
                {error.message || 'Failed to update figures for the selected range. Displaying previously loaded data.'}
              </AppText>
            </View>
            <Button
              label="Retry"
              variant="outline"
              onPress={() => void retry()}
              accessibilityLabel="Retry loading spending data for current range"
            />
          </View>
        </AppCard>
      ) : null}

      {/* Empty State Banner if 0 expenses in period */}
      {isEmpty ? (
        <AppCard style={styles.emptyCard}>
          <Ionicons name="receipt-outline" size={40} color={theme.colors.textSecondary} />
          <AppText variant="bodyStrong" color="textPrimary" style={{ marginTop: theme.spacing.sm }}>
            No expenses found in this period
          </AppText>
          <AppText variant="body" color="textSecondary" style={{ textAlign: 'center', marginTop: 4 }}>
            Try expanding the date range above to view your spending trends.
          </AppText>
        </AppCard>
      ) : (
        <>
          {/* Trend Chart */}
          <SpendingTrendChart
            buckets={trends?.buckets || []}
            totalPaise={totalAmount}
            granularity={granularity}
            onGranularityChange={setGranularity}
            viewMode={viewMode}
            disabled={isLoading || isRefreshing}
          />

          {/* Category Breakdown Chart */}
          <CategoryBreakdownChart
            categories={categories?.categories || []}
            totalPaise={totalAmount}
            viewMode={viewMode}
          />

          {/* Table Toggle Button */}
          <View style={styles.tableToggleRow}>
            <Button
              label={showTableView ? 'Hide Detailed Table' : 'Show Detailed Table'}
              variant="outline"
              fullWidth
              onPress={() => setShowTableView((prev) => !prev)}
              accessibilityLabel="Toggle accessible detailed table view"
            />
          </View>

          {/* Accessible Table View */}
          {showTableView && (
            <SpendingTableView
              buckets={trends?.buckets || []}
              categories={categories?.categories || []}
              totalPaise={totalAmount}
              viewMode={viewMode}
            />
          )}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 16,
    gap: 16,
  },
  centerContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  subtitle: {
    marginTop: 2,
    fontSize: 13,
  },
  emptyCard: {
    padding: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  inlineErrorCard: {
    padding: 12,
    borderWidth: 1,
  },
  inlineErrorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  inlineErrorTextCol: {
    flex: 1,
  },
  tableToggleRow: {
    marginTop: 4,
  },
});
