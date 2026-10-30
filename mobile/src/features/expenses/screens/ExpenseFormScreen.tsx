/**
 * US-07 / US-09 / US-26 – Add / Edit expense form screen (T-19 + T-23b).
 *
 * Shared between add and edit modes.  Pass `expense` as a route param to open
 * in edit mode; omit it for the add flow.
 *
 * Fields (per product spec, "Add or edit expense" screen):
 *   • Amount (INR, converted to paise on submit)
 *   • Date (YYYY-MM-DD, today by default)
 *   • Category chip picker  ← SuggestionChip appears here (T-23b)
 *   • Payment mode chip picker
 *   • Notes / description (optional, 500 char max)  ← drives suggestion
 *   • Recurring toggle
 *
 * Error states handled:
 *   • Field validation (inline)
 *   • Save failed: banner with Retry; form keeps all values (US-07)
 *   • Version conflict: "This expense changed – review" banner (US-09)
 *   • Cancel button always available
 */

import React, { useRef } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import type { Expense, PaymentMode } from '../types';
import {
  CATEGORIES,
  PAYMENT_MODE_LABELS,
  PAYMENT_MODES,
} from '../types';
import { useExpenseForm } from '../hooks/useExpenseForm';
import { useCategorySuggestion } from '../hooks/useCategorySuggestion';
import { SuggestionChip } from '../components/SuggestionChip';

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ExpenseFormScreenProps {
  /** Present when the screen is opened in edit mode. */
  existingExpense?: Expense;
  onSuccess: (saved: Expense) => void;
  onCancel: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ExpenseFormScreen({
  existingExpense,
  onSuccess,
  onCancel,
}: ExpenseFormScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const notesRef = useRef<TextInput>(null);

  const {
    values,
    fieldErrors,
    isLoading,
    submitError,
    hasConflict,
    isEditMode,
    handleFieldChange,
    handleSubmit,
    handleRetry,
    handleCancel,
    clearConflict,
  } = useExpenseForm({ existingExpense, onSuccess, onCancel });

  // T-23b: debounced category suggestion driven by the Notes field (US-26).
  const {
    suggestion,
    isLoading: isSuggesting,
    accept: acceptSuggestion,
    override: overrideSuggestion,
    dismiss: dismissSuggestion,
  } = useCategorySuggestion({
    description: values.notes,
    currentCategoryId: values.categoryId,
  });

  /** Accept suggestion: fill categoryId and post feedback. */
  const handleAcceptSuggestion = () => {
    const categoryId = acceptSuggestion();
    if (categoryId) handleFieldChange('categoryId', categoryId);
  };

  /** User picked a category manually while a suggestion was visible. */
  const handleCategorySelect = (categoryId: string) => {
    if (suggestion && categoryId !== suggestion.categoryId) {
      overrideSuggestion(categoryId);
    }
    handleFieldChange('categoryId', categoryId);
  };

  const title = isEditMode ? 'Edit Expense' : 'Add Expense';

  return (
    <View
      style={[
        styles.root,
        { backgroundColor: theme.colors.background },
      ]}
    >
      {/* ── Header ──────────────────────────────────────────────────── */}
      <View
        style={[
          styles.header,
          {
            paddingTop: insets.top + theme.spacing.sm,
            paddingHorizontal: theme.spacing.lg,
            paddingBottom: theme.spacing.md,
            borderBottomColor: theme.colors.border,
            backgroundColor: theme.colors.surface,
          },
        ]}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Cancel"
          disabled={isLoading}
          onPress={handleCancel}
          style={({ pressed }) => [
            styles.cancelBtn,
            { minHeight: theme.minTouchTarget, minWidth: theme.minTouchTarget },
            pressed && styles.pressed,
          ]}
        >
          <AppText variant="body" color="textPrimary">
            Cancel
          </AppText>
        </Pressable>

        <AppText variant="heading" color="textPrimary" style={styles.headerTitle}>
          {title}
        </AppText>

        {/* Right placeholder to keep title centred */}
        <View style={styles.headerRight} />
      </View>

      {/* ── Scrollable form body ─────────────────────────────────────── */}
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[
          styles.scrollContent,
          {
            paddingHorizontal: theme.spacing.lg,
            paddingTop: theme.spacing.xl,
            paddingBottom: insets.bottom + theme.spacing.xxxl,
            gap: theme.spacing.lg,
          },
        ]}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        showsVerticalScrollIndicator={false}
      >
        {/* ── Version conflict banner (US-09) ─────────────────────── */}
        {hasConflict && (
          <ConflictBanner onDismiss={clearConflict} />
        )}

        {/* ── Submit error banner ──────────────────────────────────── */}
        {submitError && (
          <ErrorBanner
            message={submitError.message}
            isRetryable={submitError.isRetryable}
            onRetry={handleRetry}
          />
        )}

        {/* ── Amount ──────────────────────────────────────────────── */}
        <AppInput
          label="Amount (₹)"
          value={values.amountRaw}
          onChangeText={(text) => handleFieldChange('amountRaw', text)}
          placeholder="0.00"
          keyboardType="decimal-pad"
          returnKeyType="next"
          onSubmitEditing={() => notesRef.current?.focus()}
          error={fieldErrors.amountRaw}
          disabled={isLoading}
          accessibilityLabel="Amount in rupees"
          accessibilityHint="Enter the expense amount in rupees, for example 250 or 1234.50"
        />

        {/* ── Date ────────────────────────────────────────────────── */}
        <AppInput
          label="Date"
          value={values.date}
          onChangeText={(text) => handleFieldChange('date', text)}
          placeholder="YYYY-MM-DD"
          keyboardType="numbers-and-punctuation"
          returnKeyType="next"
          maxLength={10}
          error={fieldErrors.date}
          disabled={isLoading}
          accessibilityLabel="Expense date"
          accessibilityHint="Enter the date in year-month-day format"
        />

        {/* ── Category chips ───────────────────────────────────────── */}
        <View style={{ gap: theme.spacing.sm }}>
          <AppText variant="small" color={isLoading ? 'textSecondary' : 'textPrimary'}>
            Category
          </AppText>
          <View style={styles.chipRow}>
            {CATEGORIES.map((cat) => {
              const isSelected = values.categoryId === cat.id;
              const palette = theme.categoryPalette[cat.paletteIndex];
              return (
                <Pressable
                  key={cat.id}
                  accessibilityRole="radio"
                  accessibilityLabel={cat.label}
                  accessibilityState={{ selected: isSelected, disabled: isLoading }}
                  disabled={isLoading}
                  onPress={() => handleCategorySelect(cat.id)}
                  style={({ pressed }) => [
                    styles.chip,
                    {
                      borderRadius: theme.radii.sm,
                      paddingVertical: theme.spacing.xs,
                      paddingHorizontal: theme.spacing.md,
                      minHeight: theme.minTouchTarget,
                      backgroundColor: isSelected
                        ? palette.soft
                        : theme.colors.surfaceMuted,
                      borderWidth: isSelected ? 1.5 : 1,
                      borderColor: isSelected
                        ? palette.fill
                        : theme.colors.border,
                      opacity: pressed ? 0.7 : 1,
                    },
                  ]}
                >
                  <AppText
                    variant="caption"
                    style={{
                      color: isSelected
                        ? palette.fill
                        : theme.colors.textSecondary,
                      fontFamily: isSelected
                        ? theme.fontFamily.semibold
                        : theme.fontFamily.regular,
                    }}
                  >
                    {cat.label}
                  </AppText>
                </Pressable>
              );
            })}
          </View>
          {fieldErrors.categoryId ? (
            <AppText
              variant="caption"
              color="negative"
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
            >
              {`[!] ${fieldErrors.categoryId}`}
            </AppText>
          ) : null}
        </View>

        {/* ── Payment mode chips ───────────────────────────────────── */}
        <View style={{ gap: theme.spacing.sm }}>
          <AppText variant="small" color={isLoading ? 'textSecondary' : 'textPrimary'}>
            Payment Mode
          </AppText>
          <View style={styles.chipRow}>
            {PAYMENT_MODES.map((mode) => {
              const isSelected = values.paymentMode === mode;
              return (
                <Pressable
                  key={mode}
                  accessibilityRole="radio"
                  accessibilityLabel={PAYMENT_MODE_LABELS[mode]}
                  accessibilityState={{ selected: isSelected, disabled: isLoading }}
                  disabled={isLoading}
                  onPress={() =>
                    handleFieldChange('paymentMode', mode as PaymentMode)
                  }
                  style={({ pressed }) => [
                    styles.chip,
                    {
                      borderRadius: theme.radii.sm,
                      paddingVertical: theme.spacing.xs,
                      paddingHorizontal: theme.spacing.md,
                      minHeight: theme.minTouchTarget,
                      backgroundColor: isSelected
                        ? theme.colors.info.soft
                        : theme.colors.surfaceMuted,
                      borderWidth: isSelected ? 1.5 : 1,
                      borderColor: isSelected
                        ? theme.colors.info.fill
                        : theme.colors.border,
                      opacity: pressed ? 0.7 : 1,
                    },
                  ]}
                >
                  <AppText
                    variant="caption"
                    style={{
                      color: isSelected
                        ? theme.colors.info.text
                        : theme.colors.textSecondary,
                      fontFamily: isSelected
                        ? theme.fontFamily.semibold
                        : theme.fontFamily.regular,
                    }}
                  >
                    {PAYMENT_MODE_LABELS[mode]}
                  </AppText>
                </Pressable>
              );
            })}
          </View>
          {fieldErrors.paymentMode ? (
            <AppText
              variant="caption"
              color="negative"
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
            >
              {`[!] ${fieldErrors.paymentMode}`}
            </AppText>
          ) : null}
        </View>

        {/* ── Notes ───────────────────────────────────────────────── */}
        <View style={{ gap: theme.spacing.sm }}>
          <AppInput
            ref={notesRef}
            label="Notes (optional)"
            value={values.notes}
            onChangeText={(text) => handleFieldChange('notes', text)}
            placeholder="What was this for?"
            returnKeyType="done"
            multiline
            numberOfLines={3}
            error={fieldErrors.notes}
            disabled={isLoading}
            inputStyle={styles.notesInput}
            accessibilityLabel="Expense notes"
            accessibilityHint="Optional description for this expense"
          />
          <AppText variant="caption" color="textSecondary" style={styles.charCount}>
            {values.notes.length}/500
          </AppText>

          {/* T-23b: suggestion chip driven by the notes/description field */}
          <SuggestionChip
            suggestedCategoryId={suggestion?.categoryId ?? null}
            confidence={suggestion?.confidence}
            isLoading={isSuggesting}
            onAccept={handleAcceptSuggestion}
            onDismiss={dismissSuggestion}
            disabled={isLoading}
          />
        </View>

        {/* ── Recurring toggle ─────────────────────────────────────── */}
        <View
          style={[
            styles.toggleRow,
            {
              backgroundColor: theme.colors.surface,
              borderColor: theme.colors.border,
              borderRadius: theme.radii.md,
              padding: theme.spacing.md,
            },
          ]}
        >
          <View style={styles.toggleLabel}>
            <AppText variant="body" color="textPrimary">
              Recurring
            </AppText>
            <AppText variant="caption" color="textSecondary">
              Repeat this expense monthly
            </AppText>
          </View>
          <Switch
            value={values.isRecurring}
            onValueChange={(val) => handleFieldChange('isRecurring', val)}
            disabled={isLoading}
            accessibilityLabel="Recurring expense toggle"
            accessibilityHint="Toggle to mark this as a recurring monthly expense"
            trackColor={{
              false: theme.colors.border,
              true: theme.colors.info.fill,
            }}
            thumbColor={
              Platform.OS === 'android'
                ? values.isRecurring
                  ? theme.colors.info.text
                  : theme.colors.textSecondary
                : undefined
            }
          />
        </View>

        {/* ── Submit button ────────────────────────────────────────── */}
        <Button
          label={isEditMode ? 'Save Changes' : 'Add Expense'}
          variant="primary"
          fullWidth
          loading={isLoading}
          disabled={isLoading}
          onPress={handleSubmit}
          accessibilityLabel={
            isEditMode
              ? 'Save changes to this expense'
              : 'Add this expense to your records'
          }
        />
      </ScrollView>
    </View>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ConflictBanner({ onDismiss }: { onDismiss: () => void }) {
  const theme = useTheme();
  return (
    <View
      accessibilityRole="alert"
      accessibilityLiveRegion="assertive"
      style={[
        styles.banner,
        {
          backgroundColor: theme.colors.warning.soft,
          borderColor: theme.colors.warning.text,
          borderRadius: theme.radii.md,
          padding: theme.spacing.md,
          gap: theme.spacing.sm,
        },
      ]}
    >
      <AppText variant="small" color="warning">
        {'[!] This expense changed – review before saving.'}
      </AppText>
      <Button
        label="Dismiss"
        variant="outline"
        onPress={onDismiss}
        accessibilityLabel="Dismiss conflict warning"
      />
    </View>
  );
}

interface ErrorBannerProps {
  message: string;
  isRetryable?: boolean;
  onRetry?: () => void;
}

function ErrorBanner({ message, isRetryable, onRetry }: ErrorBannerProps) {
  const theme = useTheme();
  return (
    <View
      accessibilityRole="alert"
      accessibilityLiveRegion="assertive"
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
        {`[!] ${message}`}
      </AppText>
      {isRetryable && onRetry && (
        <Button
          label="Try again"
          variant="outline"
          onPress={onRetry}
          accessibilityLabel="Retry saving this expense"
        />
      )}
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: 1,
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
  },
  cancelBtn: {
    justifyContent: 'center',
    alignItems: 'flex-start',
  },
  headerRight: {
    // Mirror cancelBtn width so title stays centred
    width: 56,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  notesInput: {
    minHeight: 72,
    textAlignVertical: 'top',
    paddingTop: 10,
  },
  charCount: {
    alignSelf: 'flex-end',
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
  },
  toggleLabel: {
    flex: 1,
    gap: 2,
    marginRight: 12,
  },
  banner: {
    width: '100%',
    borderWidth: 1,
  },
  pressed: {
    opacity: 0.6,
  },
});
