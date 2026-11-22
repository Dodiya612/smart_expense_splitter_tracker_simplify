import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { SkeletonBox, SkeletonCard, SkeletonText } from '@/components/ui/Skeleton';
import { WakingUpBanner } from '@/components/ui/WakingUpBanner';
import { useTheme } from '@/theme';

export interface ExpenseHistorySkeletonProps {
  showWakingUp?: boolean;
}

/**
 * Layout-accurate skeleton screen for the Transaction History (ExpenseHistoryScreen).
 * Mirrors the search bar, category chips, and expense list item card hierarchy.
 */
export function ExpenseHistorySkeleton({ showWakingUp = false }: ExpenseHistorySkeletonProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[
        styles.root,
        {
          backgroundColor: theme.colors.background,
          paddingHorizontal: theme.spacing.lg,
          paddingTop: insets.top + theme.spacing.md,
          paddingBottom: insets.bottom + theme.spacing.xxxl,
          gap: theme.spacing.md,
        },
      ]}
    >
      {showWakingUp && <WakingUpBanner />}

      {/* 1. Header Bar: Title + Add Button */}
      <View style={styles.titleRow}>
        <View style={{ flex: 1, gap: 4 }}>
          <SkeletonText width={180} variant="heading" />
          <SkeletonText width={120} variant="caption" />
        </View>
        <SkeletonBox width={72} height={36} borderRadius={theme.radii.md} />
      </View>

      {/* 2. Search Input Skeleton */}
      <SkeletonBox width="100%" height={48} borderRadius={theme.radii.md} />

      {/* 3. Category Filter Chips Horizontal Placeholder */}
      <View style={[styles.categoryChipsRow, { gap: theme.spacing.xs }]}>
        {[48, 64, 76, 80, 70].map((w, idx) => (
          <SkeletonBox
            key={idx}
            width={w}
            height={32}
            borderRadius={theme.radii.pill}
          />
        ))}
      </View>

      {/* 4. Expense List Item Card Skeletons */}
      {[1, 2, 3, 4].map((itemKey) => (
        <SkeletonCard key={itemKey} style={{ gap: theme.spacing.sm }}>
          <View style={styles.topRow}>
            <SkeletonBox width={84} height={24} borderRadius={theme.radii.pill} />
            <SkeletonText width={100} variant="title" />
          </View>
          <View style={[styles.metaRow, { gap: 8 }]}>
            <SkeletonText width={70} variant="caption" />
            <SkeletonText width={80} variant="caption" />
          </View>
          <SkeletonText width="60%" variant="small" />
          <View style={[styles.actionsRow, { gap: theme.spacing.sm }]}>
            <SkeletonBox width={60} height={28} borderRadius={theme.radii.sm} />
            <SkeletonBox width={60} height={28} borderRadius={theme.radii.sm} />
          </View>
        </SkeletonCard>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  categoryChipsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    overflow: 'hidden',
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  actionsRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginTop: 4,
  },
});
