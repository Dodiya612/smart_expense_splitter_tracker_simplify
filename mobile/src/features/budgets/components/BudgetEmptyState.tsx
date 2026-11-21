/**
 * BudgetEmptyState Component (T-49 / US-25).
 *
 * Explains what to do when no budgets exist, with a prominent primary CTA button.
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';

export interface BudgetEmptyStateProps {
  onCreatePress: () => void;
  isFiltered?: boolean;
  onClearFilter?: () => void;
}

export function BudgetEmptyState({
  onCreatePress,
  isFiltered = false,
  onClearFilter,
}: BudgetEmptyStateProps) {
  const theme = useTheme();

  return (
    <AppCard
      accessibilityRole="summary"
      accessibilityLabel={
        isFiltered
          ? 'No budgets match the selected filter. Try clearing filters or create a new budget.'
          : 'No budgets created yet. Set a weekly or monthly budget to track spending.'
      }
      style={[styles.container, { padding: theme.spacing.xl, gap: theme.spacing.md }]}
    >
      <View
        style={[
          styles.iconCircle,
          {
            backgroundColor: theme.colors.surfaceMuted,
            borderRadius: theme.radii.pill,
          },
        ]}
      >
        <Ionicons name="wallet-outline" size={36} color={theme.colors.primary} />
      </View>

      <View style={styles.textGroup}>
        <AppText variant="title" color="textPrimary" style={styles.textCenter}>
          {isFiltered ? 'No budgets found' : 'Set your first budget'}
        </AppText>
        <AppText variant="body" color="textSecondary" style={styles.textCenter}>
          {isFiltered
            ? 'There are no active budgets for this filter view.'
            : 'Track your spending against weekly or monthly limits. We will alert you at 80% and 100% of your limit.'}
        </AppText>
      </View>

      <View style={[styles.btnGroup, { gap: theme.spacing.sm }]}>
        <Button
          label="Create a budget"
          variant="primary"
          onPress={onCreatePress}
          accessibilityLabel="Create a new budget"
        />
        {isFiltered && onClearFilter && (
          <Button
            label="View all budgets"
            variant="outline"
            onPress={onClearFilter}
            accessibilityLabel="Clear filter and view all budgets"
          />
        )}
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    marginVertical: 16,
  },
  iconCircle: {
    width: 64,
    height: 64,
    justifyContent: 'center',
    alignItems: 'center',
  },
  textGroup: {
    alignItems: 'center',
    gap: 6,
  },
  textCenter: {
    textAlign: 'center',
  },
  btnGroup: {
    width: '100%',
    marginTop: 8,
  },
});
