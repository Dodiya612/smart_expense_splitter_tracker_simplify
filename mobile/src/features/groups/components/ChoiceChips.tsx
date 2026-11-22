import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';

export interface ChoiceOption {
  id: string;
  label: string;
}

export interface ChoiceChipsProps {
  label: string;
  options: readonly ChoiceOption[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  error?: string;
}

/** Single-choice chips (category, who paid). Selection shown by border, weight and a check. */
export function ChoiceChips({ label, options, selectedId, onSelect, error }: ChoiceChipsProps) {
  const theme = useTheme();

  return (
    <View style={{ gap: theme.spacing.xs }}>
      <AppText variant="small">{label}</AppText>
      <View style={[styles.wrap, { gap: theme.spacing.sm }]} accessibilityRole="radiogroup" accessibilityLabel={label}>
        {options.map((option) => {
          const selected = option.id === selectedId;
          return (
            <Pressable
              key={option.id}
              accessibilityRole="radio"
              accessibilityState={{ checked: selected }}
              accessibilityLabel={option.label}
              onPress={() => onSelect(option.id)}
              style={({ pressed }) => [
                styles.chip,
                {
                  minHeight: theme.minTouchTarget,
                  paddingHorizontal: theme.spacing.md,
                  gap: theme.spacing.xs,
                  borderRadius: theme.radii.pill,
                  borderWidth: selected ? 2 : 1,
                  borderColor: selected ? theme.colors.primary : theme.colors.borderStrong,
                  backgroundColor: selected ? theme.colors.surfaceMuted : theme.colors.surface,
                },
                pressed && styles.pressed,
              ]}>
              {selected ? <Ionicons name="checkmark" size={16} color={theme.colors.primary} /> : null}
              <AppText variant={selected ? 'bodyStrong' : 'small'}>{option.label}</AppText>
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
  wrap: { flexDirection: 'row', flexWrap: 'wrap' },
  chip: { flexDirection: 'row', alignItems: 'center' },
  pressed: { opacity: 0.7 },
});
