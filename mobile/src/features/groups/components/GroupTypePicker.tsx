import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { GROUP_TYPES, type GroupType } from '../types';
import { groupTypeInfo } from '../utils/groupDisplay';

export interface GroupTypePickerProps {
  value: GroupType | null;
  onChange: (type: GroupType) => void;
  error?: string;
}

/** Friends / Flat / Trip / Family selector (FR-14). Selection shown by border, icon and check. */
export function GroupTypePicker({ value, onChange, error }: GroupTypePickerProps) {
  const theme = useTheme();

  return (
    <View style={{ gap: theme.spacing.xs }}>
      <AppText variant="small">Group type</AppText>
      <View style={[styles.grid, { gap: theme.spacing.sm }]} accessibilityRole="radiogroup">
        {GROUP_TYPES.map((type) => {
          const info = groupTypeInfo(type);
          const selected = value === type;
          return (
            <Pressable
              key={type}
              accessibilityRole="radio"
              accessibilityState={{ checked: selected }}
              accessibilityLabel={info.label}
              onPress={() => onChange(type)}
              style={({ pressed }) => [
                styles.option,
                {
                  minHeight: theme.minTouchTarget,
                  borderRadius: theme.radii.md,
                  paddingHorizontal: theme.spacing.md,
                  gap: theme.spacing.sm,
                  backgroundColor: selected ? theme.colors.surfaceMuted : theme.colors.surface,
                  borderColor: selected ? theme.colors.primary : theme.colors.borderStrong,
                  borderWidth: selected ? 2 : 1,
                },
                pressed && styles.pressed,
              ]}>
              <Ionicons name={info.icon} size={20} color={theme.colors.textPrimary} />
              <AppText variant={selected ? 'bodyStrong' : 'body'} style={styles.label}>
                {info.label}
              </AppText>
              {selected ? (
                <Ionicons name="checkmark-circle" size={18} color={theme.colors.primary} />
              ) : null}
            </Pressable>
          );
        })}
      </View>
      {error ? (
        <AppText variant="caption" color="negative" accessibilityRole="alert">
          {`[!] ${error}`}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  option: { flexDirection: 'row', alignItems: 'center', flexGrow: 1, flexBasis: '45%' },
  label: { flex: 1 },
  pressed: { opacity: 0.7 },
});
