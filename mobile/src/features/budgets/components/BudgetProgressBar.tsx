/**
 * BudgetProgressBar Component (T-49 / US-25).
 *
 * Horizontal linear progress bar (strictly NOT a category donut)
 * exposing full accessibility attributes (role, value, and textual label).
 */

import React from 'react';
import { DimensionValue, StyleSheet, View } from 'react-native';
import { useTheme } from '@/theme';
import type { BudgetStatus } from '../types';

export interface BudgetProgressBarProps {
  percentUsed: number;
  status: BudgetStatus;
  height?: number;
  testID?: string;
  accessibilityLabel?: string;
}

export function BudgetProgressBar({
  percentUsed,
  status,
  height = 8,
  testID = 'budget-progress-bar',
  accessibilityLabel,
}: BudgetProgressBarProps) {
  const theme = useTheme();

  // Clamp percentage from 0 to 100 for visual fill width
  const visualPercentage = Math.max(0, Math.min(100, isNaN(percentUsed) ? 0 : percentUsed));
  const progressWidth: DimensionValue = `${visualPercentage}%`;

  // Semantic color coding based on backend status
  const getProgressColor = () => {
    switch (status) {
      case 'exceeded':
        return theme.colors.negative.fill;
      case 'warning':
        return theme.colors.warning.fill;
      case 'under':
      default:
        return theme.colors.primary;
    }
  };

  const defaultA11yLabel = `Budget progress: ${visualPercentage} percent used, status: ${status}.`;

  return (
    <View
      testID={testID}
      accessibilityRole="progressbar"
      accessibilityValue={{
        min: 0,
        max: 100,
        now: visualPercentage,
      }}
      accessibilityLabel={accessibilityLabel || defaultA11yLabel}
      style={[
        styles.track,
        {
          height,
          backgroundColor: theme.colors.surfaceMuted,
          borderRadius: theme.radii.pill,
        },
      ]}
    >
      <View
        testID={`${testID}-fill`}
        style={[
          styles.fill,
          {
            width: progressWidth,
            height,
            backgroundColor: getProgressColor(),
            borderRadius: theme.radii.pill,
          },
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    width: '100%',
    overflow: 'hidden',
  },
  fill: {
    minWidth: 2,
  },
});
