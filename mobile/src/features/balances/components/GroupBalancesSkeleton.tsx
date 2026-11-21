import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { SkeletonBox, SkeletonCard, SkeletonCircle, SkeletonText } from '@/components/ui/Skeleton';
import { WakingUpBanner } from '@/components/ui/WakingUpBanner';
import { useTheme } from '@/theme';

export interface GroupBalancesSkeletonProps {
  showWakingUp?: boolean;
}

/**
 * Layout-accurate skeleton screen for the Group Balances & Settle Up screen (GroupBalancesScreen).
 * Renders placeholders for group net position, simplification card, and peer balance rows.
 */
export function GroupBalancesSkeleton({ showWakingUp = false }: GroupBalancesSkeletonProps) {
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

      {/* 1. Title Row */}
      <View style={styles.titleRow}>
        <View style={{ flex: 1, gap: 4 }}>
          <SkeletonText width={160} variant="heading" />
          <SkeletonText width={140} variant="caption" />
        </View>
      </View>

      {/* 2. Net Position Card Skeleton */}
      <SkeletonCard style={{ gap: theme.spacing.md }}>
        <View style={styles.rowBetween}>
          <SkeletonText width={120} variant="caption" />
          <SkeletonText width={140} variant="title" />
        </View>
        <View style={[styles.splitGrid, { gap: theme.spacing.md }]}>
          <View style={[styles.splitBox, { backgroundColor: theme.colors.surfaceMuted, borderRadius: theme.radii.md, padding: theme.spacing.sm }]}>
            <SkeletonText width={80} variant="caption" />
            <SkeletonText width={90} variant="body" style={{ marginTop: 4 }} />
          </View>
          <View style={[styles.splitBox, { backgroundColor: theme.colors.surfaceMuted, borderRadius: theme.radii.md, padding: theme.spacing.sm }]}>
            <SkeletonText width={80} variant="caption" />
            <SkeletonText width={90} variant="body" style={{ marginTop: 4 }} />
          </View>
        </View>
      </SkeletonCard>

      {/* 3. Simplify Debts Card Skeleton */}
      <SkeletonCard style={{ padding: theme.spacing.sm }}>
        <View style={styles.rowBetween}>
          <View style={{ gap: 4, flex: 1 }}>
            <SkeletonText width={130} variant="body" />
            <SkeletonText width={200} variant="caption" />
          </View>
          <SkeletonBox width={48} height={28} borderRadius={theme.radii.pill} />
        </View>
      </SkeletonCard>

      {/* 4. Member Balance Rows Skeletons */}
      {[1, 2, 3].map((idx) => (
        <SkeletonCard key={idx} style={{ padding: theme.spacing.md }}>
          <View style={styles.rowBetween}>
            <View style={[styles.memberInfo, { gap: theme.spacing.sm }]}>
              <SkeletonCircle size={40} />
              <View style={{ gap: 4 }}>
                <SkeletonText width={110} variant="body" />
                <SkeletonText width={80} variant="caption" />
              </View>
            </View>
            <View style={{ alignItems: 'flex-end', gap: 6 }}>
              <SkeletonText width={80} variant="title" />
              <SkeletonBox width={68} height={28} borderRadius={theme.radii.sm} />
            </View>
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
    paddingBottom: 4,
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
  memberInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
});
