import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';

export function DashboardEmptyState() {
  const theme = useTheme();

  const handleAddExpense = () => {
    router.push('/add-expense' as Href);
  };

  return (
    <AppCard
      style={[
        styles.container,
        {
          padding: theme.spacing.xl,
          gap: theme.spacing.md,
        },
      ]}
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
        <Ionicons name="receipt-outline" size={32} color={theme.colors.primary} />
      </View>

      <View style={[styles.textBlock, { gap: theme.spacing.xs }]}>
        <AppText variant="heading" color="textPrimary" style={styles.centerText}>
          No expenses recorded yet
        </AppText>
        <AppText variant="body" color="textSecondary" style={styles.centerText}>
          Expenses added this month will appear here, tracking your spending, category budgets, and shared balances.
        </AppText>
      </View>

      <Button
        label="+ Add Your First Expense"
        variant="primary"
        fullWidth
        accessibilityLabel="Add your first expense"
        accessibilityHint="Navigates to the Add Expense modal"
        onPress={handleAddExpense}
        style={{ marginTop: theme.spacing.sm }}
      />
    </AppCard>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
  },
  iconCircle: {
    width: 64,
    height: 64,
    alignItems: 'center',
    justifyContent: 'center',
  },
  textBlock: {
    alignItems: 'center',
    maxWidth: 300,
  },
  centerText: {
    textAlign: 'center',
  },
});
