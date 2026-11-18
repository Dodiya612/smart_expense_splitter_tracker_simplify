import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { SplitMode, SplitPreview } from '@/utils/splits';
import { splitSummaryText } from '../utils/splitSummary';

export interface SplitSummaryProps {
  mode: SplitMode;
  preview: SplitPreview;
}

export function SplitSummary({ mode, preview }: SplitSummaryProps) {
  const theme = useTheme();
  const ok = preview.isBalanced;
  const palette = ok ? theme.colors.positive : theme.colors.warning;

  return (
    <View
      accessibilityRole="summary"
      accessibilityLiveRegion="polite"
      style={[
        styles.row,
        { gap: theme.spacing.sm, padding: theme.spacing.md, borderRadius: theme.radii.md, backgroundColor: palette.soft },
      ]}>
      <Ionicons name={ok ? 'checkmark-circle-outline' : 'alert-circle-outline'} size={20} color={palette.text} />
      <AppText variant="bodyStrong" color={ok ? 'positive' : 'warning'} style={styles.flex}>
        {splitSummaryText(mode, preview)}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  flex: { flex: 1 },
});
