import React from 'react';
import { Pressable, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '@/theme';

export interface TabBarAddButtonProps {
  onPress: () => void;
}

export function TabBarAddButton({ onPress }: TabBarAddButtonProps) {
  const theme = useTheme();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Add expense"
      accessibilityHint="Opens modal to create a new expense"
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        {
          width: theme.minTouchTarget,
          height: theme.minTouchTarget,
          borderRadius: theme.radii.pill,
          backgroundColor: pressed ? theme.colors.primaryPressed : theme.colors.primary,
          ...(pressed ? { elevation: 0, shadowOpacity: 0 } : theme.shadows.button),
        },
      ]}>
      <Ionicons name="add" size={26} color={theme.colors.textOnPrimary} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
