/**
 * Date Range Selector Component (T-43 / US-12).
 *
 * Allows 1M, 3M, 6M, 1Y presets and an interactive Custom date range form.
 * Start and end dates are entered via clean theme-styled AppInput fields with
 * inline validation (format checking, start <= end, and 731-day max range limit).
 */

import React, { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { AppCard } from '@/components/ui/AppCard';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import type { DateRangePreset } from '../types';
import { validateDateRange } from '../utils/dateRange';

export interface DateRangeSelectorProps {
  preset: DateRangePreset;
  onSelectPreset: (preset: DateRangePreset) => void;
  onSelectCustomRange: (from: string, to: string) => void;
  fromDate: string;
  toDate: string;
  disabled?: boolean;
}

const PRESETS: { id: DateRangePreset; label: string }[] = [
  { id: '1M', label: '1M' },
  { id: '3M', label: '3M' },
  { id: '6M', label: '6M' },
  { id: '1Y', label: '1Y' },
  { id: 'custom', label: 'Custom' },
];

export function DateRangeSelector({
  preset,
  onSelectPreset,
  onSelectCustomRange,
  fromDate,
  toDate,
  disabled,
}: DateRangeSelectorProps) {
  const theme = useTheme();

  // Local state for custom date inputs
  const [customFrom, setCustomFrom] = useState<string>(fromDate);
  const [customTo, setCustomTo] = useState<string>(toDate);
  const [customError, setCustomError] = useState<string | null>(null);

  const handlePresetPress = (id: DateRangePreset) => {
    setCustomError(null);
    onSelectPreset(id);
    if (id === 'custom') {
      setCustomFrom(fromDate);
      setCustomTo(toDate);
    }
  };

  const handleApplyCustom = () => {
    const trimmedFrom = customFrom.trim();
    const trimmedTo = customTo.trim();

    const validation = validateDateRange(trimmedFrom, trimmedTo);
    if (!validation.isValid) {
      setCustomError(validation.error || 'Invalid date range.');
      return;
    }

    setCustomError(null);
    onSelectCustomRange(trimmedFrom, trimmedTo);
  };

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <AppText variant="caption" color="textSecondary">
          Active: {fromDate} to {toDate}
        </AppText>
      </View>

      <View
        style={[
          styles.pillRow,
          {
            backgroundColor: theme.colors.surfaceMuted,
            borderRadius: theme.radii.pill,
            borderColor: theme.colors.border,
          },
        ]}
        accessibilityRole="tablist"
        accessibilityLabel="Date range preset"
      >
        {PRESETS.map((p) => {
          const isSelected = preset === p.id;
          return (
            <Pressable
              key={p.id}
              disabled={disabled}
              onPress={() => handlePresetPress(p.id)}
              accessibilityRole="tab"
              accessibilityState={{ selected: isSelected }}
              accessibilityLabel={`Select ${p.label} date range`}
              style={[
                styles.pill,
                isSelected && [
                  styles.pillActive,
                  theme.shadows.card,
                  { backgroundColor: theme.colors.surface, borderRadius: theme.radii.pill },
                ],
              ]}
            >
              <AppText
                variant={isSelected ? 'bodyStrong' : 'caption'}
                color={isSelected ? 'textPrimary' : 'textSecondary'}
              >
                {p.label}
              </AppText>
            </Pressable>
          );
        })}
      </View>

      {/* Custom Date Range Picker Accordion / Panel */}
      {preset === 'custom' && (
        <AppCard
          style={[
            styles.customPanel,
            {
              backgroundColor: theme.colors.surfaceMuted,
              borderColor: theme.colors.border,
              borderRadius: theme.radii.md,
            },
          ]}
        >
          <AppText variant="bodyStrong" color="textPrimary">
            Custom Date Range
          </AppText>

          <View style={styles.inputRow}>
            <View style={styles.inputCol}>
              <AppInput
                label="From"
                placeholder="YYYY-MM-DD"
                value={customFrom}
                onChangeText={(text) => {
                  setCustomFrom(text);
                  setCustomError(null);
                }}
                maxLength={10}
                keyboardType="numbers-and-punctuation"
                disabled={disabled}
                accessibilityLabel="Custom range start date"
              />
            </View>

            <View style={styles.inputCol}>
              <AppInput
                label="To"
                placeholder="YYYY-MM-DD"
                value={customTo}
                onChangeText={(text) => {
                  setCustomTo(text);
                  setCustomError(null);
                }}
                maxLength={10}
                keyboardType="numbers-and-punctuation"
                disabled={disabled}
                accessibilityLabel="Custom range end date"
              />
            </View>
          </View>

          {customError && (
            <AppText variant="caption" color="negative">
              {customError}
            </AppText>
          )}

          <Button
            label="Apply Range"
            variant="primary"
            fullWidth
            disabled={disabled}
            onPress={handleApplyCustom}
            accessibilityLabel="Apply custom date range"
          />
        </AppCard>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  pillRow: {
    flexDirection: 'row',
    padding: 3,
    borderWidth: 1,
  },
  pill: {
    flex: 1,
    paddingVertical: 6,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
  },
  pillActive: {},
  customPanel: {
    padding: 12,
    borderWidth: 1,
    gap: 10,
  },
  inputRow: {
    flexDirection: 'row',
    gap: 12,
  },
  inputCol: {
    flex: 1,
  },
});
