import React, { useEffect, useRef } from 'react';
import {
  Animated,
  DimensionValue,
  StyleProp,
  StyleSheet,
  View,
  ViewStyle,
} from 'react-native';
import { useTheme } from '@/theme';

export interface SkeletonBoxProps {
  width?: DimensionValue;
  height?: DimensionValue;
  borderRadius?: number;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}

/**
 * Primitive skeleton loading element with gentle pulse animation.
 * Adheres strictly to the project design system using useTheme().
 */
export function SkeletonBox({
  width = '100%',
  height = 16,
  borderRadius,
  style,
  children,
}: SkeletonBoxProps) {
  const theme = useTheme();
  const pulseAnim = useRef(new Animated.Value(0.45)).current;

  useEffect(() => {
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 0.9,
          duration: 800,
          useNativeDriver: true,
        }),
        Animated.timing(pulseAnim, {
          toValue: 0.45,
          duration: 800,
          useNativeDriver: true,
        }),
      ])
    );
    pulse.start();
    return () => pulse.stop();
  }, [pulseAnim]);

  const radius = borderRadius ?? theme.radii.sm;

  return (
    <Animated.View
      accessibilityElementsHidden={true}
      importantForAccessibility="no-hide-descendants"
      style={[
        styles.box,
        {
          width,
          height,
          borderRadius: radius,
          backgroundColor: theme.colors.surfaceMuted,
          opacity: pulseAnim,
        },
        style,
      ]}
    >
      {children}
    </Animated.View>
  );
}

export interface SkeletonTextProps {
  width?: DimensionValue;
  variant?: 'heading' | 'title' | 'body' | 'caption' | 'small' | 'money';
  style?: StyleProp<ViewStyle>;
}

export function SkeletonText({
  width = '100%',
  variant = 'body',
  style,
}: SkeletonTextProps) {
  const theme = useTheme();

  const heightByVariant: Record<string, number> = {
    heading: 28,
    title: 22,
    body: 16,
    caption: 12,
    small: 10,
    money: 32,
  };

  const height = heightByVariant[variant] || 16;

  return (
    <SkeletonBox
      width={width}
      height={height}
      borderRadius={theme.radii.sm}
      style={style}
    />
  );
}

export interface SkeletonCircleProps {
  size?: number;
  style?: StyleProp<ViewStyle>;
}

export function SkeletonCircle({ size = 40, style }: SkeletonCircleProps) {
  const theme = useTheme();
  return (
    <SkeletonBox
      width={size}
      height={size}
      borderRadius={theme.radii.pill}
      style={style}
    />
  );
}

export interface SkeletonCardProps {
  height?: DimensionValue;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}

export function SkeletonCard({ height, style, children }: SkeletonCardProps) {
  const theme = useTheme();

  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.md,
          gap: theme.spacing.md,
          ...theme.shadows.card,
        },
        height ? { height } : null,
        style,
      ]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    overflow: 'hidden',
  },
  card: {
    borderWidth: 1,
    width: '100%',
  },
});
