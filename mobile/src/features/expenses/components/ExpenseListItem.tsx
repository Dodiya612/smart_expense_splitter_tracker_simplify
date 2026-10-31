/**
 * ExpenseListItem – T-20 / US-08 / US-13
 *
 * A single row in the expense list.  Shows date, category chip, amount and
 * notes summary.  Exposes delete and edit actions both as:
 *   • Visible buttons (for mouse and keyboard users, per US-13)
 *   • The `onDelete` / `onEdit` callbacks (for swipe actions on touch screens)
 *
 * This component does NOT own the delete-confirm dialog or the undo toast;
 * those are managed by `useDeleteExpense` in the parent screen so one toast
 * is shared across the whole list.
 *
 * Usage:
 *   <ExpenseListItem
 *     expense={expense}
 *     onEdit={handleEdit}
 *     onDelete={handleDelete}
 *   />
 */

import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { CATEGORIES, PAYMENT_MODE_LABELS } from '../types';
import type { Expense } from '../types';

export interface ExpenseListItemProps {
  expense: Expense;
  onEdit: (expense: Expense) => void;
  onDelete: (expense: Expense) => void;
}

export function ExpenseListItem({ expense, onEdit, onDelete }: ExpenseListItemProps) {
  const theme = useTheme();

  const category = CATEGORIES.find((c) => c.id === expense.categoryId);
  const palette = category ? theme.categoryPalette[category.paletteIndex] : null;
  const amountInr = (expense.amountPaise / 100).toLocaleString('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
  });

  return (
    <View
      style={[
        styles.row,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.md,
          gap: theme.spacing.sm,
          ...theme.shadows.card,
        },
      ]}
      accessibilityRole="listitem"
    >
      {/* ── Top row: category chip + amount ─────────────────────── */}
      <View style={styles.topRow}>
        {category && palette ? (
          <View
            style={[
              styles.categoryChip,
              {
                backgroundColor: palette.soft,
                borderRadius: theme.radii.pill,
                paddingHorizontal: theme.spacing.md,
                paddingVertical: theme.spacing.xs,
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
        ) : (
          <View />
        )}

        <AppText variant="money" color="textPrimary">
          {amountInr}
        </AppText>
      </View>

      {/* ── Meta row: date + payment mode ───────────────────────── */}
      <View style={styles.metaRow}>
        <AppText variant="caption" color="textSecondary">
          {expense.date}
        </AppText>
        <AppText variant="caption" color="textSecondary">
          {'·'}
        </AppText>
        <AppText variant="caption" color="textSecondary">
          {PAYMENT_MODE_LABELS[expense.paymentMode]}
        </AppText>
        {expense.isRecurring && (
          <>
            <AppText variant="caption" color="textSecondary">{'·'}</AppText>
            <AppText variant="caption" color="info">↺ Recurring</AppText>
          </>
        )}
      </View>

      {/* ── Notes summary ───────────────────────────────────────── */}
      {expense.notes ? (
        <AppText variant="small" color="textSecondary" numberOfLines={1}>
          {expense.notes}
        </AppText>
      ) : null}

      {/* ── Action buttons (visible for mouse/keyboard – US-13) ─── */}
      <View style={[styles.actions, { gap: theme.spacing.sm }]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Edit expense ${amountInr} on ${expense.date}`}
          onPress={() => onEdit(expense)}
          style={({ pressed }) => [
            styles.actionBtn,
            {
              backgroundColor: theme.colors.surfaceMuted,
              borderColor: theme.colors.border,
              borderRadius: theme.radii.sm,
              paddingVertical: theme.spacing.xs,
              paddingHorizontal: theme.spacing.md,
              minHeight: theme.minTouchTarget,
            },
            pressed && styles.pressed,
          ]}
        >
          <AppText variant="caption" color="textPrimary">
            Edit
          </AppText>
        </Pressable>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Delete expense ${amountInr} on ${expense.date}`}
          onPress={() => onDelete(expense)}
          style={({ pressed }) => [
            styles.actionBtn,
            {
              backgroundColor: theme.colors.negative.soft,
              borderColor: theme.colors.negative.text,
              borderRadius: theme.radii.sm,
              paddingVertical: theme.spacing.xs,
              paddingHorizontal: theme.spacing.md,
              minHeight: theme.minTouchTarget,
            },
            pressed && styles.pressed,
          ]}
        >
          <AppText variant="caption" color="negative">
            Delete
          </AppText>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    borderWidth: 1,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  categoryChip: {
    alignSelf: 'flex-start',
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexWrap: 'wrap',
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginTop: 4,
  },
  actionBtn: {
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
  },
  pressed: {
    opacity: 0.65,
  },
});
