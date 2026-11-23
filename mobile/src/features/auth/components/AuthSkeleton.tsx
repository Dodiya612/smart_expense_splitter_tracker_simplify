import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { SkeletonBox, SkeletonCard, SkeletonText } from '@/components/ui/Skeleton';
import { useTheme } from '@/theme';

export function AuthSkeleton() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[
        styles.root,
        {
          backgroundColor: theme.colors.background,
          paddingHorizontal: theme.spacing.lg,
          paddingTop: insets.top + theme.spacing.xxxl,
          paddingBottom: insets.bottom + theme.spacing.xl,
          gap: theme.spacing.xl,
        },
      ]}
    >
      <View style={{ alignItems: 'center', gap: 8, marginVertical: 16 }}>
        <SkeletonBox width={48} height={48} borderRadius={theme.radii.md} />
        <SkeletonText width={160} variant="heading" />
        <SkeletonText width={220} variant="caption" />
      </View>

      <SkeletonCard style={{ gap: theme.spacing.lg, padding: theme.spacing.lg }}>
        <View style={{ gap: 6 }}>
          <SkeletonText width={60} variant="caption" />
          <SkeletonBox width="100%" height={48} borderRadius={theme.radii.md} />
        </View>
        <View style={{ gap: 6 }}>
          <SkeletonText width={80} variant="caption" />
          <SkeletonBox width="100%" height={48} borderRadius={theme.radii.md} />
        </View>
        <SkeletonBox width="100%" height={48} borderRadius={theme.radii.md} style={{ marginTop: 8 }} />
      </SkeletonCard>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: 'center',
  },
});
