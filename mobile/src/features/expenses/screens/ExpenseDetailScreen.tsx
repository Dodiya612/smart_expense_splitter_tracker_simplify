/**
 * ExpenseDetailScreen – US-13: Recent Expenses (Expense Detail View)
 *
 * Displays full details of a selected transaction:
 *   - Exact monetary amount in INR (integer paise, NFR-M01)
 *   - Full localized date and time
 *   - Category chip with theme palette styling
 *   - Payment mode label
 *   - Notes and description
 *   - Merchant name (if present)
 *   - Recurring status
 *
 * Actions:
 *   - Back action (accessible button & header back)
 *   - Delete action (reusing T-20 ConfirmDialog and UndoToast via useDeleteExpense)
 *
 * Safe handling:
 *   - Handles missing or malformed expense data gracefully with a dedicated empty state.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { UndoToast } from '@/components/ui/UndoToast';
import { useTheme } from '@/theme';
import {
  CATEGORIES,
  PAYMENT_MODE_LABELS,
  type Expense,
} from '../types';
import { useDeleteExpense } from '../hooks/useDeleteExpense';

export interface ExpenseDetailScreenProps {
  expense?: Expense;
  onBack?: () => void;
}

/** Formats integer paise into standard Indian Rupee currency format (e.g. ₹1,499.50). */
export function formatPaiseToInr(amountPaise: number): string {
  const inrValue = amountPaise / 100;
  return inrValue.toLocaleString('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Formats date and optional creation time into a human-readable localized string. */
export function formatFullDateTime(dateStr?: string, createdAtStr?: string): string {
  const target = createdAtStr || dateStr;
  if (!target) return '—';
  try {
    const d = new Date(target);
    if (isNaN(d.getTime())) return dateStr || '—';
    const hasTime = !!createdAtStr && createdAtStr.includes('T');
    return d.toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: hasTime ? 'numeric' : undefined,
      minute: hasTime ? '2-digit' : undefined,
      hour12: true,
    });
  } catch {
    return dateStr || '—';
  }
}

export function ExpenseDetailScreen({
  expense: propExpense,
  onBack,
}: ExpenseDetailScreenProps = {}) {
  const theme = useTheme();
  const params = useLocalSearchParams<{ expense?: string }>();
  const [isDeleted, setIsDeleted] = useState(false);

  // Safely resolve expense: prop first, then route param JSON parsing
  const expense = useMemo<Expense | undefined>(() => {
    if (propExpense) return propExpense;
    if (params.expense) {
      try {
        return JSON.parse(params.expense) as Expense;
      } catch {
        return undefined;
      }
    }
    return undefined;
  }, [propExpense, params.expense]);

  const handleBack = useCallback(() => {
    if (onBack) {
      onBack();
      return;
    }
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace('/(tabs)/home');
    }
  }, [onBack]);

  // Reusing existing T-20 delete-with-confirm and 10s undo flow
  const {
    confirmDialogVisible,
    toastVisible,
    deleteError,
    isDeleting,
    requestDelete,
    handleConfirmDelete,
    handleCancelDelete,
    handleUndo,
    handleToastDismissed,
    clearDeleteError,
  } = useDeleteExpense({
    onDeleted: () => {
      setIsDeleted(true);
    },
    onRestored: () => {
      setIsDeleted(false);
    },
  });

  const onToastDismissed = useCallback(() => {
    handleToastDismissed();
    // When deletion is permanent, return to previous screen
    if (isDeleted) {
      handleBack();
    }
  }, [handleToastDismissed, isDeleted, handleBack]);

  // ── Missing / Malformed Expense Safe State ───────────────────────────────────
  if (!expense) {
    return (
      <ScreenContainer scrollable>
        <View style={[styles.container, { gap: theme.spacing.lg }]}>
          {/* Header */}
          <View style={styles.headerRow}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Go back"
              accessibilityHint="Navigates to the previous screen"
              onPress={handleBack}
              style={({ pressed }) => [
                styles.backButton,
                {
                  minHeight: theme.minTouchTarget,
                  minWidth: theme.minTouchTarget,
                  borderRadius: theme.radii.pill,
                  backgroundColor: theme.colors.surfaceMuted,
                },
                pressed && styles.pressed,
              ]}
            >
              <Ionicons name="arrow-back" size={20} color={theme.colors.textPrimary} />
            </Pressable>
            <AppText variant="heading" color="textPrimary">
              Expense Details
            </AppText>
            <View style={styles.headerSpacer} />
          </View>

          {/* Missing state card */}
          <AppCard style={{ alignItems: 'center', padding: theme.spacing.xl, gap: theme.spacing.md }}>
            <View
              style={[
                styles.iconCircle,
                {
                  backgroundColor: theme.colors.surfaceMuted,
                  borderRadius: theme.radii.pill,
                },
              ]}
            >
              <Ionicons name="alert-circle-outline" size={36} color={theme.colors.warning.text} />
            </View>
            <AppText variant="heading" color="textPrimary" style={styles.centerText}>
              Expense details unavailable
            </AppText>
            <AppText variant="body" color="textSecondary" style={styles.centerText}>
              Could not load the requested expense. The record may have been removed or the link is invalid.
            </AppText>
            <Button
              label="Go Back"
              variant="primary"
              fullWidth
              onPress={handleBack}
              accessibilityLabel="Go back"
              style={{ marginTop: theme.spacing.sm }}
            />
          </AppCard>
        </View>
      </ScreenContainer>
    );
  }

  // ── Populated Expense Metadata ───────────────────────────────────────────────
  const category = CATEGORIES.find((c) => c.id === expense.categoryId);
  const palette = category ? theme.categoryPalette[category.paletteIndex] : null;
  const formattedAmount = formatPaiseToInr(expense.amountPaise);
  const formattedDateTime = formatFullDateTime(expense.date, expense.createdAt);
  const paymentModeLabel = PAYMENT_MODE_LABELS[expense.paymentMode] || expense.paymentMode;

  return (
    <ScreenContainer scrollable>
      <View style={[styles.container, { gap: theme.spacing.lg }]}>
        {/* ── Screen Header ─────────────────────────────────────── */}
        <View style={styles.headerRow}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Go back"
            accessibilityHint="Navigates to the previous screen"
            onPress={handleBack}
            style={({ pressed }) => [
              styles.backButton,
              {
                minHeight: theme.minTouchTarget,
                minWidth: theme.minTouchTarget,
                borderRadius: theme.radii.pill,
                backgroundColor: theme.colors.surfaceMuted,
              },
              pressed && styles.pressed,
            ]}
          >
            <Ionicons name="arrow-back" size={20} color={theme.colors.textPrimary} />
          </Pressable>
          <AppText variant="heading" color="textPrimary">
            Expense Details
          </AppText>
          <View style={styles.headerSpacer} />
        </View>

        {/* ── Delete Error Banner ───────────────────────────────── */}
        {deleteError && (
          <View
            accessibilityRole="alert"
            style={[
              styles.banner,
              {
                backgroundColor: theme.colors.negative.soft,
                borderColor: theme.colors.negative.text,
                borderRadius: theme.radii.md,
                padding: theme.spacing.md,
                gap: theme.spacing.sm,
              },
            ]}
          >
            <AppText variant="small" color="negative">
              {`[!] ${deleteError.message}`}
            </AppText>
            <Button
              label="Dismiss"
              variant="outline"
              onPress={clearDeleteError}
              accessibilityLabel="Dismiss error"
            />
          </View>
        )}

        {/* ── Deleted Notice Banner ─────────────────────────────── */}
        {isDeleted && (
          <View
            accessibilityRole="alert"
            style={[
              styles.banner,
              {
                backgroundColor: theme.colors.surfaceMuted,
                borderColor: theme.colors.border,
                borderRadius: theme.radii.md,
                padding: theme.spacing.md,
                gap: 4,
              },
            ]}
          >
            <AppText variant="bodyStrong" color="textPrimary">
              Expense queued for deletion
            </AppText>
            <AppText variant="caption" color="textSecondary">
              Tap Undo in the notification below within 10 seconds to restore it.
            </AppText>
          </View>
        )}

        {/* ── Amount & Category Highlight Card ──────────────────── */}
        <AppCard style={{ alignItems: 'center', paddingVertical: theme.spacing.xl, gap: theme.spacing.sm }}>
          <AppText variant="caption" color="textSecondary">
            Total Amount
          </AppText>
          <AppText variant="moneyLarge" color="textPrimary">
            {formattedAmount}
          </AppText>

          <View style={[styles.badgeRow, { gap: theme.spacing.xs, marginTop: theme.spacing.xs }]}>
            {category && palette && (
              <View
                style={[
                  styles.categoryPill,
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
            )}

            {expense.isRecurring && (
              <View
                style={[
                  styles.recurringPill,
                  {
                    backgroundColor: theme.colors.info.soft,
                    borderRadius: theme.radii.pill,
                    paddingHorizontal: theme.spacing.md,
                    paddingVertical: theme.spacing.xs,
                  },
                ]}
              >
                <AppText variant="caption" color="info" style={{ fontFamily: theme.fontFamily.semibold }}>
                  ↺ Recurring
                </AppText>
              </View>
            )}
          </View>
        </AppCard>

        {/* ── Detailed Properties Card ──────────────────────────── */}
        <AppCard style={{ gap: theme.spacing.md }}>
          <AppText variant="bodyStrong" color="textPrimary">
            Transaction Information
          </AppText>

          {/* Date & Time */}
          <View style={styles.attributeRow}>
            <AppText variant="small" color="textSecondary">
              Date & Time
            </AppText>
            <AppText variant="bodyStrong" color="textPrimary">
              {formattedDateTime}
            </AppText>
          </View>

          <View style={[styles.divider, { backgroundColor: theme.colors.border }]} />

          {/* Payment Mode */}
          <View style={styles.attributeRow}>
            <AppText variant="small" color="textSecondary">
              Payment Mode
            </AppText>
            <AppText variant="bodyStrong" color="textPrimary">
              {paymentModeLabel}
            </AppText>
          </View>

          {/* Merchant (if available) */}
          {expense.merchant ? (
            <>
              <View style={[styles.divider, { backgroundColor: theme.colors.border }]} />
              <View style={styles.attributeRow}>
                <AppText variant="small" color="textSecondary">
                  Merchant / Store
                </AppText>
                <AppText variant="bodyStrong" color="textPrimary">
                  {expense.merchant}
                </AppText>
              </View>
            </>
          ) : null}

          {/* Notes / Description */}
          <View style={[styles.divider, { backgroundColor: theme.colors.border }]} />
          <View style={styles.notesBlock}>
            <AppText variant="small" color="textSecondary">
              Notes & Description
            </AppText>
            <AppText variant="body" color="textPrimary" style={{ marginTop: 4 }}>
              {expense.notes || expense.description || 'No notes added.'}
            </AppText>
          </View>
        </AppCard>

        {/* ── Visible Actions Section ───────────────────────────── */}
        <View style={[styles.actionsSection, { gap: theme.spacing.sm }]}>
          <Button
            label="Delete Expense"
            variant="destructive"
            fullWidth
            loading={isDeleting}
            disabled={isDeleting || isDeleted}
            onPress={() => requestDelete(expense)}
            accessibilityLabel={`Delete expense ${formattedAmount}`}
            accessibilityHint="Opens confirmation dialog to delete this expense"
          />

          <Button
            label="Back"
            variant="outline"
            fullWidth
            onPress={handleBack}
            accessibilityLabel="Back to previous screen"
          />
        </View>
      </View>

      {/* ── T-20: Confirm Delete Dialog (US-08) ─────────────────── */}
      <ConfirmDialog
        visible={confirmDialogVisible}
        title="Delete expense?"
        message={`Delete ${formattedAmount} on ${expense.date}? You'll have 10 seconds to undo.`}
        confirmLabel="Delete"
        cancelLabel="Keep it"
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        isLoading={isDeleting}
      />

      {/* ── T-20: 10-Second Undo Toast (US-08) ──────────────────── */}
      <UndoToast
        visible={toastVisible}
        message="Expense deleted"
        durationMs={10_000}
        onUndo={handleUndo}
        onDismissed={onToastDismissed}
      />
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  container: {
    width: '100%',
    paddingBottom: 24,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    paddingVertical: 8,
  },
  backButton: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerSpacer: {
    width: 44,
  },
  pressed: {
    opacity: 0.7,
  },
  centerText: {
    textAlign: 'center',
  },
  iconCircle: {
    width: 64,
    height: 64,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    justifyContent: 'center',
  },
  categoryPill: {
    alignSelf: 'flex-start',
  },
  recurringPill: {
    alignSelf: 'flex-start',
  },
  attributeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
  },
  divider: {
    height: 1,
    width: '100%',
  },
  notesBlock: {
    width: '100%',
  },
  banner: {
    borderWidth: 1,
    width: '100%',
  },
  actionsSection: {
    width: '100%',
    marginTop: 8,
  },
});