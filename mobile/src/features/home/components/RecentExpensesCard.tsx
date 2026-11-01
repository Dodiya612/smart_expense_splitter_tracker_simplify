import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { CATEGORIES, PAYMENT_MODE_LABELS } from '@/features/expenses/types';
import type { Expense } from '@/features/expenses/types';
import { formatPaiseToInr } from '../utils/dashboardSummary';

export interface RecentExpensesCardProps {
  expenses: Expense[];
}

export function RecentExpensesCard({ expenses }: RecentExpensesCardProps) {
  const theme = useTheme();

  const handleAddPress = () => {
    router.push('/add-expense' as Href);
  };

  const displayExpenses = expenses.slice(0, 3);

  return (
    <AppCard style={{ gap: theme.spacing.sm }}>
      {/* ── Card Header ────────────────────────────────────────── */}
      <View style={styles.cardHeader}>
        <View style={[styles.titleRow, { gap: theme.spacing.xs }]}>
          <Ionicons name="receipt-outline" size={18} color={theme.colors.primary} />
          <AppText variant="bodyStrong" color="textPrimary">
            Recent expenses
          </AppText>
        </View>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Add expense"
          accessibilityHint="Navigates to the Add Expense modal"
          onPress={handleAddPress}
          style={({ pressed }) => [
            styles.addActionButton,
            {
              backgroundColor: theme.colors.surfaceMuted,
              borderRadius: theme.radii.sm,
              paddingHorizontal: theme.spacing.sm,
              paddingVertical: theme.spacing.xs,
              minHeight: theme.minTouchTarget,
            },
            pressed && { opacity: 0.75 },
          ]}
        >
          <AppText variant="caption" color="textPrimary">
            + Add
          </AppText>
        </Pressable>
      </View>

      {/* ── Expenses List (Presentational demo items) ───────────── */}
      <View style={styles.listContainer}>
        {displayExpenses.map((expense, index) => {
          const category = CATEGORIES.find((c) => c.id === expense.categoryId);
          const palette = category ? theme.categoryPalette[category.paletteIndex] : null;
          const formattedAmount = formatPaiseToInr(expense.amountPaise);
          const isLast = index === displayExpenses.length - 1;

          return (
            <View
              key={expense.id}
              accessibilityRole="summary"
              accessibilityLabel={`${expense.notes || category?.label || 'Expense'}, ${formattedAmount} on ${expense.date}`}
              style={[
                styles.itemRow,
                {
                  paddingVertical: theme.spacing.sm,
                  borderBottomColor: theme.colors.border,
                  borderBottomWidth: isLast ? 0 : 1,
                  minHeight: theme.minTouchTarget,
                },
              ]}
            >
              <View style={[styles.itemLeft, { gap: 6 }]}>
                {/* Category chip + Title */}
                <View style={[styles.categoryAndTitle, { gap: 6 }]}>
                  {category && palette && (
                    <View
                      style={[
                        styles.chip,
                        {
                          backgroundColor: palette.soft,
                          borderRadius: theme.radii.pill,
                          paddingHorizontal: theme.spacing.xs + 2,
                          paddingVertical: 2,
                        },
                      ]}
                    >
                      <AppText
                        variant="caption"
                        style={{ color: palette.fill, fontFamily: theme.fontFamily.semibold }}
                      >
                        {category.label}
                      </AppText>
                    </View>
                  )}

                  <AppText
                    variant="bodyStrong"
                    color="textPrimary"
                    numberOfLines={1}
                    style={styles.itemTitle}
                  >
                    {expense.notes || category?.label || 'Expense'}
                  </AppText>
                </View>

                {/* Date & payment mode */}
                <View style={styles.metaRow}>
                  <AppText variant="caption" color="textSecondary">
                    {expense.date}
                  </AppText>
                  <AppText variant="caption" color="textSecondary">
                    {'·'}
                  </AppText>
                  <AppText variant="caption" color="textSecondary">
                    {PAYMENT_MODE_LABELS[expense.paymentMode] || expense.paymentMode}
                  </AppText>
                  {expense.isRecurring && (
                    <>
                      <AppText variant="caption" color="textSecondary">
                        {'·'}
                      </AppText>
                      <AppText variant="caption" color="info">
                        Recurring
                      </AppText>
                    </>
                  )}
                </View>
              </View>

              {/* Amount */}
              <View style={styles.itemRight}>
                <AppText variant="money" color="textPrimary">
                  {formattedAmount}
                </AppText>
              </View>
            </View>
          );
        })}
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  addActionButton: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  listContainer: {
    width: '100%',
  },
  itemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
  },
  itemLeft: {
    flex: 1,
    paddingRight: 8,
  },
  categoryAndTitle: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  chip: {
    alignSelf: 'flex-start',
  },
  itemTitle: {
    flexShrink: 1,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    flexWrap: 'wrap',
  },
  itemRight: {
    alignItems: 'flex-end',
    justifyContent: 'center',
  },
});
