import React from 'react';
import {
  AccessibilityRole,
  Pressable,
  StyleProp,
  StyleSheet,
  View,
  ViewStyle,
} from 'react-native';
import { useTheme } from '@/theme';

export interface AppCardProps {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  onPress?: () => void;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  accessibilityRole?: AccessibilityRole;
}

export function AppCard({
  children,
  style,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  accessibilityRole = 'button',
}: AppCardProps) {
  const theme = useTheme();

  const cardStyle: ViewStyle = {
    backgroundColor: theme.colors.surface,
    borderColor: theme.colors.border,
    borderWidth: 1,
    borderRadius: theme.radii.lg,
    padding: theme.spacing.md,
    ...theme.shadows.card,
  };

  if (onPress) {
    return (
      <Pressable
        accessibilityRole={accessibilityRole}
        accessibilityLabel={accessibilityLabel}
        accessibilityHint={accessibilityHint}
        onPress={onPress}
        style={({ pressed }) => [
          styles.base,
          cardStyle,
          { minHeight: theme.minTouchTarget },
          pressed && [styles.pressed, { elevation: 1, shadowOpacity: 0.04 }],
          style,
        ]}>
        {children}
      </Pressable>
    );
  }

  return (
    <View style={[styles.base, cardStyle, style]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  base: {
    width: '100%',
  },
  pressed: {
    opacity: 0.88,
  },
});
