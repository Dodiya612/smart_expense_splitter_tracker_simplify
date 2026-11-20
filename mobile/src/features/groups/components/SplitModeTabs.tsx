import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { SPLIT_MODES, type SplitMode } from '@/utils/splits';

export const SPLIT_MODE_LABELS: Record<SplitMode, string> = {
  equal: 'Equally',
  exact: 'Amounts',
  percentage: 'Percent',
  parts: 'Parts',
};

export interface SplitModeTabsProps {
  mode: SplitMode;
  onChange: (mode: SplitMode) => void;
}

/** Equal / exact / percentage / parts switch for the split editor (T-31). */
export function SplitModeTabs({ mode, onChange }: SplitModeTabsProps) {
  const theme = useTheme();

  return (
    <View
      accessibilityRole="tablist"
      style={[
        styles.row,
        { backgroundColor: theme.colors.surfaceMuted, borderRadius: theme.radii.md, padding: theme.spacing.xs },
      ]}>
      {SPLIT_MODES.map((m) => {
        const selected = m === mode;
        return (
          <Pressable
            key={m}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            accessibilityLabel={`Split ${SPLIT_MODE_LABELS[m].toLowerCase()}`}
            onPress={() => onChange(m)}
            style={({ pressed }) => [
              styles.tab,
              {
                minHeight: theme.minTouchTarget,
                borderRadius: theme.radii.sm,
                backgroundColor: selected ? theme.colors.surface : 'transparent',
              },
              selected && theme.shadows.button,
              pressed && styles.pressed,
            ]}>
            <AppText variant={selected ? 'bodyStrong' : 'small'} color={selected ? 'textPrimary' : 'textSecondary'}>
              {SPLIT_MODE_LABELS[m]}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row' },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  pressed: { opacity: 0.7 },
});
