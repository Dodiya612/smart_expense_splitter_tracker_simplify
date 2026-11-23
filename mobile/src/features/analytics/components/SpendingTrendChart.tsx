/**
 * Spending Trend Chart Component (T-43 / US-12).
 *
 * Implements:
 * - Granularity toggle (Day / Week / Month).
 * - Pure React Native responsive vertical bars with height proportional to highest value.
 * - Tooltip/Callout on bar press showing exact date and formatted INR paise.
 * - Running cumulative indicator line or header figure.
 * - 100% theme token compliant, no hardcoded colors.
 */

import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { formatPaiseToInr } from '@/features/home/utils/dashboardSummary';
import { useTheme } from '@/theme';
import type { AnalyticsGranularity, SpendingViewMode, TrendBucket } from '../types';

export interface SpendingTrendChartProps {
  buckets: TrendBucket[];
  totalPaise: number;
  granularity: AnalyticsGranularity;
  onGranularityChange: (g: AnalyticsGranularity) => void;
  viewMode: SpendingViewMode;
  disabled?: boolean;
}

export function SpendingTrendChart({
  buckets,
  totalPaise,
  granularity,
  onGranularityChange,
  viewMode,
  disabled,
}: SpendingTrendChartProps) {
  const theme = useTheme();
  const [selectedBucketIndex, setSelectedBucketIndex] = useState<number | null>(null);

  // Maximum value for proportional bar height
  const maxPaise = Math.max(
    ...buckets.map((b) => (viewMode === 'share' ? b.sharePaise : b.cashPaidPaise)),
    1000 // avoid division by 0
  );

  const selectedBucket = selectedBucketIndex !== null && buckets[selectedBucketIndex]
    ? buckets[selectedBucketIndex]
    : buckets[buckets.length - 1] ?? null;

  const selectedAmount = selectedBucket
    ? viewMode === 'share' ? selectedBucket.sharePaise : selectedBucket.cashPaidPaise
    : totalPaise;

  const selectedCumulative = selectedBucket
    ? viewMode === 'share' ? selectedBucket.cumulativeSharePaise : selectedBucket.cumulativeCashPaidPaise
    : totalPaise;

  const GRANULARITIES: { id: AnalyticsGranularity; label: string }[] = [
    { id: 'day', label: 'Day' },
    { id: 'week', label: 'Week' },
    { id: 'month', label: 'Month' },
  ];

  return (
    <AppCard style={styles.card}>
      {/* Top Header Row with Granularity Selector */}
      <View style={styles.headerRow}>
        <View style={styles.titleCol}>
          <AppText variant="caption" color="textSecondary">
            {viewMode === 'share' ? 'Total Share Spent' : 'Total Cash Paid'}
          </AppText>
          <AppText variant="heading" color="textPrimary" style={styles.headlineTotal}>
            {formatPaiseToInr(totalPaise)}
          </AppText>
        </View>

        {/* Granularity Chips */}
        <View
          style={[
            styles.granularityContainer,
            {
              backgroundColor: theme.colors.surfaceMuted,
              borderRadius: theme.radii.pill,
              borderColor: theme.colors.border,
            },
          ]}
          accessibilityRole="tablist"
          accessibilityLabel="Trend granularity"
        >
          {GRANULARITIES.map((g) => {
            const isSelected = granularity === g.id;
            return (
              <Pressable
                key={g.id}
                disabled={disabled}
                onPress={() => {
                  setSelectedBucketIndex(null);
                  onGranularityChange(g.id);
                }}
                accessibilityRole="tab"
                accessibilityState={{ selected: isSelected }}
                accessibilityLabel={`${g.label} granularity`}
                style={[
                  styles.granularityTab,
                  isSelected && [
                    styles.granularityTabActive,
                    theme.shadows.card,
                    { backgroundColor: theme.colors.surface, borderRadius: theme.radii.pill },
                  ],
                ]}
              >
                <AppText
                  variant={isSelected ? 'bodyStrong' : 'caption'}
                  color={isSelected ? 'textPrimary' : 'textSecondary'}
                  style={styles.granularityText}
                >
                  {g.label}
                </AppText>
              </Pressable>
            );
          })}
        </View>
      </View>

      {/* Selected Bucket Detail Banner */}
      {selectedBucket && (
        <View
          style={[
            styles.detailBanner,
            {
              backgroundColor: theme.colors.surfaceMuted,
              borderRadius: theme.radii.sm,
              borderColor: theme.colors.border,
            },
          ]}
        >
          <View style={styles.detailItem}>
            <AppText variant="caption" color="textSecondary">
              {granularity === 'day'
                ? selectedBucket.bucketStart
                : `${selectedBucket.bucketStart} - ${selectedBucket.bucketEnd}`}
            </AppText>
            <AppText variant="bodyStrong" color="textPrimary">
              {formatPaiseToInr(selectedAmount)}
            </AppText>
          </View>
          <View style={[styles.detailItem, { alignItems: 'flex-end' }]}>
            <AppText variant="caption" color="textSecondary">
              Running Cumulative
            </AppText>
            <AppText variant="body" color="textPrimary">
              {formatPaiseToInr(selectedCumulative)}
            </AppText>
          </View>
        </View>
      )}

      {/* Bar Chart Visualization */}
      <View style={styles.chartContainer}>
        {buckets.length === 0 ? (
          <View style={styles.emptyContainer}>
            <AppText variant="body" color="textSecondary">
              No trend data available for this range.
            </AppText>
          </View>
        ) : (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.barsScrollContent}
          >
            {buckets.map((bucket, index) => {
              const amount = viewMode === 'share' ? bucket.sharePaise : bucket.cashPaidPaise;
              const isSelected = selectedBucketIndex === index;
              const heightRatio = Math.max(amount / maxPaise, 0.04);
              const barHeight = Math.round(heightRatio * 120);

              // Label short format (DD or MMM or W#)
              let label = bucket.bucketStart.slice(8); // DD
              if (granularity === 'month') {
                label = bucket.bucketStart.slice(5, 7); // MM
              } else if (granularity === 'week') {
                label = `${bucket.bucketStart.slice(5, 7)}/${bucket.bucketStart.slice(8)}`;
              }

              return (
                <Pressable
                  key={`${bucket.bucketStart}-${index}`}
                  onPress={() => setSelectedBucketIndex(index)}
                  style={styles.barColumn}
                  hitSlop={{ top: 8, bottom: 8, left: 6, right: 6 }}
                  accessibilityRole="button"
                  accessibilityLabel={`Date: ${bucket.bucketStart}, Amount: ${formatPaiseToInr(amount)}`}
                >
                  <View style={styles.barTrack}>
                    <View
                      style={[
                        styles.barFill,
                        {
                          height: barHeight,
                          backgroundColor: isSelected
                            ? theme.colors.primary
                            : amount > 0
                            ? theme.colors.info.fill
                            : theme.colors.border,
                          borderTopLeftRadius: theme.radii.sm,
                          borderTopRightRadius: theme.radii.sm,
                        },
                      ]}
                    />
                  </View>
                  <AppText
                    variant="caption"
                    color={isSelected ? 'textPrimary' : 'textSecondary'}
                    style={styles.barLabel}
                  >
                    {label}
                  </AppText>
                </Pressable>
              );
            })}
          </ScrollView>
        )}
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 16,
    gap: 12,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  titleCol: {
    flex: 1,
  },
  headlineTotal: {
    fontSize: 22,
    marginTop: 2,
  },
  granularityContainer: {
    flexDirection: 'row',
    padding: 2,
    borderWidth: 1,
  },
  granularityTab: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  granularityTabActive: {},
  granularityText: {
    fontSize: 11,
  },
  detailBanner: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: 10,
    borderWidth: 1,
  },
  detailItem: {
    gap: 2,
  },
  chartContainer: {
    height: 160,
    marginTop: 8,
    justifyContent: 'flex-end',
  },
  barsScrollContent: {
    alignItems: 'flex-end',
    paddingHorizontal: 4,
    gap: 8,
  },
  barColumn: {
    alignItems: 'center',
    width: 28,
  },
  barTrack: {
    height: 124,
    width: 14,
    justifyContent: 'flex-end',
  },
  barFill: {
    width: '100%',
  },
  barLabel: {
    marginTop: 6,
    fontSize: 10,
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
