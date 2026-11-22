import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { SkeletonBox, SkeletonText } from '@/components/ui/Skeleton';
import { useTheme } from '@/theme';

export function ExpenseFormSkeleton() {
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
          paddingBottom: insets.bottom + theme.spacing.xl,
          gap: theme.spacing.lg,
        },
      ]}
    >
      <View style={{ gap: 4 }}>
        <SkeletonText width={160} variant="heading" />
        <SkeletonText width={220} variant="caption" />
      </View>

      {/* Amount Field Skeleton */}
      <View style={{ gap: 6 }}>
        <SkeletonText width={90} variant="caption" />
        <SkeletonBox width="100%" height={56} borderRadius={theme.radii.md} />
      </View>

      {/* Category Grid Skeleton */}
      <View style={{ gap: 6 }}>
        <SkeletonText width={110} variant="caption" />
        <View style={[styles.chipsGrid, { gap: theme.spacing.xs }]}>
          {[70, 80, 75, 90, 85, 65].map((w, idx) => (
            <SkeletonBox key={idx} width={w} height={36} borderRadius={theme.radii.pill} />
          ))}
        </View>
      </View>

      {/* Date Field Skeleton */}
      <View style={{ gap: 6 }}>
        <SkeletonText width={70} variant="caption" />
        <SkeletonBox width="100%" height={48} borderRadius={theme.radii.md} />
      </View>

      {/* Button Skeleton */}
      <SkeletonBox width="100%" height={48} borderRadius={theme.radii.md} style={{ marginTop: 'auto' }} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  chipsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
});
