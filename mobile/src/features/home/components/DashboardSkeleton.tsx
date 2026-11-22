import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { SkeletonBox, SkeletonCard, SkeletonText } from '@/components/ui/Skeleton';
import { WakingUpBanner } from '@/components/ui/WakingUpBanner';
import { useTheme } from '@/theme';

export interface DashboardSkeletonProps {
  showWakingUp?: boolean;
}

/**
 * Layout-accurate skeleton screen for the main Dashboard (HomeScreen).
 * Prevents cumulative layout shifts (CLS) and delivers an immediate visual response.
 */
export function DashboardSkeleton({ showWakingUp = false }: DashboardSkeletonProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <ScreenContainer
      scrollable
      contentContainerStyle={[
        styles.scrollContent,
        {
          paddingBottom: Math.max(insets.bottom, theme.spacing.md) + 88,
          gap: theme.spacing.lg,
        },
      ]}
    >
      <View style={[styles.container, { gap: theme.spacing.lg }]}>
        {showWakingUp && <WakingUpBanner />}

        {/* 1. Header Skeleton: Month Label + Total Spent Paired Display */}
        <View style={[styles.headerSkeleton, { gap: theme.spacing.xs }]}>
          <SkeletonText width={100} variant="caption" />
          <SkeletonText width={220} variant="money" />
          <SkeletonBox width={90} height={24} borderRadius={theme.radii.pill} style={{ marginTop: 4 }} />
        </View>

        {/* 2. Balance Preview Card Skeleton */}
        <SkeletonCard style={{ gap: theme.spacing.md }}>
          <View style={[styles.rowBetween]}>
            <SkeletonText width={130} variant="body" />
            <SkeletonText width={90} variant="title" />
          </View>
          <View style={[styles.splitGrid, { gap: theme.spacing.md }]}>
            <View style={[styles.splitBox, { backgroundColor: theme.colors.surfaceMuted, borderRadius: theme.radii.md, padding: theme.spacing.sm }]}>
              <SkeletonText width={70} variant="caption" />
              <SkeletonText width={90} variant="body" style={{ marginTop: 4 }} />
            </View>
            <View style={[styles.splitBox, { backgroundColor: theme.colors.surfaceMuted, borderRadius: theme.radii.md, padding: theme.spacing.sm }]}>
              <SkeletonText width={70} variant="caption" />
              <SkeletonText width={90} variant="body" style={{ marginTop: 4 }} />
            </View>
          </View>
        </SkeletonCard>

        {/* 3. Monthly Budget Preview Card Skeleton */}
        <SkeletonCard style={{ gap: theme.spacing.sm }}>
          <View style={styles.rowBetween}>
            <SkeletonText width={140} variant="body" />
            <SkeletonText width={80} variant="body" />
          </View>
          {/* Progress bar track placeholder */}
          <SkeletonBox height={10} borderRadius={theme.radii.pill} style={{ marginVertical: 6 }} />
          <View style={styles.rowBetween}>
            <SkeletonText width={100} variant="caption" />
            <SkeletonText width={70} variant="caption" />
          </View>
        </SkeletonCard>

        {/* 4. Recent Expenses Card Skeleton */}
        <SkeletonCard style={{ gap: theme.spacing.md }}>
          <View style={styles.rowBetween}>
            <SkeletonText width={150} variant="heading" />
            <SkeletonText width={60} variant="caption" />
          </View>
          {/* 3 expense item rows */}
          {[1, 2, 3].map((key) => (
            <View key={key} style={[styles.expenseRowSkeleton, { borderTopColor: theme.colors.border, borderTopWidth: key > 1 ? 1 : 0, paddingTop: key > 1 ? theme.spacing.sm : 0, gap: theme.spacing.xs }]}>
              <View style={styles.rowBetween}>
                <SkeletonBox width={80} height={20} borderRadius={theme.radii.pill} />
                <SkeletonText width={70} variant="body" />
              </View>
              <SkeletonText width="65%" variant="caption" />
            </View>
          ))}
        </SkeletonCard>
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  scrollContent: {
    paddingTop: 16,
  },
  container: {
    flex: 1,
    width: '100%',
  },
  headerSkeleton: {
    paddingVertical: 8,
  },
  rowBetween: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  splitGrid: {
    flexDirection: 'row',
    width: '100%',
  },
  splitBox: {
    flex: 1,
  },
  expenseRowSkeleton: {
    width: '100%',
  },
});
