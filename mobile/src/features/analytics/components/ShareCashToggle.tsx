/**
 * Share / Cash Paid segmented switch (T-43 / US-12 / DR-14).
 *
 * DR-14: "Personal spending reports and budgets shall count a user's allocated share
 * of shared expenses, not the full amount they paid for others; cash paid is reported separately."
 */

import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { SpendingViewMode } from '../types';

export interface ShareCashToggleProps {
  mode: SpendingViewMode;
  onChange: (mode: SpendingViewMode) => void;
  disabled?: boolean;
}

export function ShareCashToggle({ mode, onChange, disabled }: ShareCashToggleProps) {
  const theme = useTheme();

  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: theme.colors.surfaceMuted,
          borderRadius: theme.radii.pill,
          borderColor: theme.colors.border,
        },
      ]}
      accessibilityRole="radiogroup"
      accessibilityLabel="Spending basis toggle"
    >
      <Pressable
        disabled={disabled}
        onPress={() => onChange('share')}
        accessibilityRole="radio"
        accessibilityState={{ selected: mode === 'share' }}
        accessibilityLabel="Your Share"
        accessibilityHint="Shows personal spending counting only your share of group expenses"
        style={[
          styles.segment,
          mode === 'share' && [
            styles.segmentActive,
            theme.shadows.card,
            { backgroundColor: theme.colors.surface, borderRadius: theme.radii.pill },
          ],
        ]}
      >
        <AppText
          variant={mode === 'share' ? 'bodyStrong' : 'body'}
          color={mode === 'share' ? 'textPrimary' : 'textSecondary'}
          style={styles.label}
        >
          Your Share
        </AppText>
      </Pressable>

      <Pressable
        disabled={disabled}
        onPress={() => onChange('cash_paid')}
        accessibilityRole="radio"
        accessibilityState={{ selected: mode === 'cash_paid' }}
        accessibilityLabel="Cash Paid"
        accessibilityHint="Shows total physical cash or UPI fronted by you"
        style={[
          styles.segment,
          mode === 'cash_paid' && [
            styles.segmentActive,
            theme.shadows.card,
            { backgroundColor: theme.colors.surface, borderRadius: theme.radii.pill },
          ],
        ]}
      >
        <AppText
          variant={mode === 'cash_paid' ? 'bodyStrong' : 'body'}
          color={mode === 'cash_paid' ? 'textPrimary' : 'textSecondary'}
          style={styles.label}
        >
          Cash Paid
        </AppText>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    padding: 3,
    borderWidth: 1,
  },
  segment: {
    flex: 1,
    paddingVertical: 8,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
  },
  segmentActive: {},
  label: {
    fontSize: 13,
  },
});
