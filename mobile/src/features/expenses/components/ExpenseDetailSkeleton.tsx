import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { SkeletonBox, SkeletonCard, SkeletonText } from '@/components/ui/Skeleton';
import { useTheme } from '@/theme';

export function ExpenseDetailSkeleton() {
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
        <SkeletonText width={140} variant="heading" />
        <SkeletonText width={90} variant="caption" />
      </View>

      <SkeletonCard style={{ gap: theme.spacing.md }}>
        <View style={styles.rowBetween}>
          <SkeletonBox width={90} height={24} borderRadius={theme.radii.pill} />
          <SkeletonText width={120} variant="money" />
        </View>
        <SkeletonText width={160} variant="body" />
        <SkeletonBox width="100%" height={1} />
        <View style={{ gap: 8 }}>
          <SkeletonText width="40%" variant="caption" />
          <SkeletonText width="70%" variant="body" />
        </View>
      </SkeletonCard>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  rowBetween: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
});
