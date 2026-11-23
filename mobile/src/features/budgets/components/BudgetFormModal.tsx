/**
 * BudgetFormModal Component (T-49 / US-25).
 *
 * Form for:
 * 1. Creating a new budget (Period: weekly/monthly, Scope: overall/category, Limit in INR)
 * 2. Editing an existing budget (Limit in INR only)
 *
 * Validates:
 * - Positive limit (> 0)
 * - Safe integer paise conversion
 * - Duplicate handling (409 BUDGET_EXISTS)
 */

import React, { useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import type { Budget, BudgetCreatePayload, BudgetPeriod, BudgetUpdatePayload } from '../types';
import { DEFAULT_BUDGET_CATEGORIES } from '../utils/categories';

export interface BudgetFormModalProps {
  visible: boolean;
  budgetToEdit?: Budget | null;
  onClose: () => void;
  onSubmitCreate: (payload: BudgetCreatePayload) => Promise<void>;
  onSubmitUpdate: (budgetId: string, payload: BudgetUpdatePayload) => Promise<void>;
  isSubmitting?: boolean;
}

export function BudgetFormModal({
  visible,
  budgetToEdit,
  onClose,
  onSubmitCreate,
  onSubmitUpdate,
  isSubmitting = false,
}: BudgetFormModalProps) {
  const theme = useTheme();
  const isEditing = Boolean(budgetToEdit);

  // Form state
  const [period, setPeriod] = useState<BudgetPeriod>('monthly');
  const [isOverall, setIsOverall] = useState<boolean>(true);
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null);
  const [limitRupees, setLimitRupees] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  // Initialize or reset form when opened
  useEffect(() => {
    if (!visible) return;

    if (budgetToEdit) {
      setPeriod(budgetToEdit.period);
      setIsOverall(budgetToEdit.categoryId === null);
      setSelectedCategoryId(budgetToEdit.categoryId);
      setLimitRupees(String(budgetToEdit.limitPaise / 100));
    } else {
      setPeriod('monthly');
      setIsOverall(true);
      setSelectedCategoryId(null);
      setLimitRupees('');
    }
    setError(null);
  }, [visible, budgetToEdit]);

  const handleSubmit = async () => {
    setError(null);
    const cleaned = limitRupees.trim().replace(/,/g, '');
    const num = Number(cleaned);

    if (isNaN(num) || num <= 0) {
      setError('Please enter a valid spending limit greater than ₹0.');
      return;
    }

    // Convert rupees to integer paise
    const limitPaise = Math.round(num * 100);
    if (limitPaise <= 0) {
      setError('Limit must be greater than 0 paise.');
      return;
    }

    try {
      if (isEditing && budgetToEdit) {
        await onSubmitUpdate(budgetToEdit.id, { limitPaise });
      } else {
        await onSubmitCreate({
          period,
          limitPaise,
          categoryId: isOverall ? null : selectedCategoryId,
        });
      }
      onClose();
    } catch (err: any) {
      if (err?.code === 'BUDGET_EXISTS' || err?.status === 409) {
        setError(
          `You already have an active ${period} budget for this category. Delete or edit the existing one.`
        );
      } else {
        setError(err?.message || 'Failed to save budget. Please try again.');
      }
    }
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={[styles.overlay, { backgroundColor: theme.colors.overlay }]}
      >
        <View
          style={[
            styles.modalContent,
            {
              backgroundColor: theme.colors.surface,
              borderRadius: theme.radii.lg,
              padding: theme.spacing.lg,
              gap: theme.spacing.md,
            },
          ]}
        >
          {/* ── Modal Header ─────────────────────────────────────── */}
          <View style={styles.headerRow}>
            <AppText variant="title" color="textPrimary">
              {isEditing ? 'Edit Budget Limit' : 'Create Budget'}
            </AppText>
            <TouchableOpacity
              testID="close-modal-btn"
              accessibilityRole="button"
              accessibilityLabel="Close form"
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              onPress={onClose}
              style={[styles.closeBtn, { minHeight: 44, minWidth: 44, justifyContent: 'center', alignItems: 'center' }]}
            >
              <Ionicons name="close" size={24} color={theme.colors.textSecondary} />
            </TouchableOpacity>
          </View>

          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ gap: theme.spacing.md }}>
            {/* ── Period Selector (Create mode only) ─────────────────── */}
            {!isEditing ? (
              <View style={{ gap: theme.spacing.xs }}>
                <AppText variant="bodyStrong" color="textPrimary">
                  Budget Period
                </AppText>
                <View style={[styles.segmentRow, { backgroundColor: theme.colors.surfaceMuted, borderRadius: theme.radii.md }]}>
                  <TouchableOpacity
                    testID="period-monthly-btn"
                    accessibilityRole="tab"
                    accessibilityState={{ selected: period === 'monthly' }}
                    accessibilityLabel="Monthly period"
                    style={[
                      styles.segmentBtn,
                      period === 'monthly' && {
                        backgroundColor: theme.colors.surface,
                        borderRadius: theme.radii.sm,
                        elevation: 1,
                      },
                      { minHeight: 44 },
                    ]}
                    onPress={() => setPeriod('monthly')}
                  >
                    <AppText
                      variant="bodyStrong"
                      color={period === 'monthly' ? 'textPrimary' : 'textSecondary'}
                    >
                      Monthly
                    </AppText>
                  </TouchableOpacity>

                  <TouchableOpacity
                    testID="period-weekly-btn"
                    accessibilityRole="tab"
                    accessibilityState={{ selected: period === 'weekly' }}
                    accessibilityLabel="Weekly period (Monday to Sunday)"
                    style={[
                      styles.segmentBtn,
                      period === 'weekly' && {
                        backgroundColor: theme.colors.surface,
                        borderRadius: theme.radii.sm,
                        elevation: 1,
                      },
                      { minHeight: 44 },
                    ]}
                    onPress={() => setPeriod('weekly')}
                  >
                    <AppText
                      variant="bodyStrong"
                      color={period === 'weekly' ? 'textPrimary' : 'textSecondary'}
                    >
                      Weekly
                    </AppText>
                  </TouchableOpacity>
                </View>
              </View>
            ) : null}

            {/* ── Scope Selector (Overall or Category) ───────────────── */}
            {!isEditing ? (
              <View style={{ gap: theme.spacing.xs }}>
                <AppText variant="bodyStrong" color="textPrimary">
                  Budget Scope
                </AppText>
                <View style={[styles.segmentRow, { backgroundColor: theme.colors.surfaceMuted, borderRadius: theme.radii.md }]}>
                  <TouchableOpacity
                    testID="scope-overall-btn"
                    accessibilityRole="tab"
                    accessibilityState={{ selected: isOverall }}
                    accessibilityLabel="Overall budget covering all expenses"
                    style={[
                      styles.segmentBtn,
                      isOverall && {
                        backgroundColor: theme.colors.surface,
                        borderRadius: theme.radii.sm,
                        elevation: 1,
                      },
                      { minHeight: 44 },
                    ]}
                    onPress={() => {
                      setIsOverall(true);
                      setSelectedCategoryId(null);
                    }}
                  >
                    <AppText
                      variant="bodyStrong"
                      color={isOverall ? 'textPrimary' : 'textSecondary'}
                    >
                      Overall
                    </AppText>
                  </TouchableOpacity>

                  <TouchableOpacity
                    testID="scope-category-btn"
                    accessibilityRole="tab"
                    accessibilityState={{ selected: !isOverall }}
                    accessibilityLabel="Specific category budget"
                    style={[
                      styles.segmentBtn,
                      !isOverall && {
                        backgroundColor: theme.colors.surface,
                        borderRadius: theme.radii.sm,
                        elevation: 1,
                      },
                      { minHeight: 44 },
                    ]}
                    onPress={() => {
                      setIsOverall(false);
                      if (!selectedCategoryId) {
                        setSelectedCategoryId(DEFAULT_BUDGET_CATEGORIES[0].id);
                      }
                    }}
                  >
                    <AppText
                      variant="bodyStrong"
                      color={!isOverall ? 'textPrimary' : 'textSecondary'}
                    >
                      Category
                    </AppText>
                  </TouchableOpacity>
                </View>

                {/* Category Chips List (when category scope selected) */}
                {!isOverall && (
                  <View style={[styles.categoryChipsGrid, { gap: theme.spacing.xs, marginTop: theme.spacing.xs }]}>
                    {DEFAULT_BUDGET_CATEGORIES.map((cat) => {
                      const isSelected = selectedCategoryId === cat.id;
                      return (
                        <TouchableOpacity
                          key={cat.id}
                          testID={`cat-chip-${cat.formId}`}
                          accessibilityRole="button"
                          accessibilityState={{ selected: isSelected }}
                          accessibilityLabel={`Category ${cat.name}`}
                          onPress={() => setSelectedCategoryId(cat.id)}
                          style={[
                            styles.chip,
                            {
                              backgroundColor: isSelected
                                ? theme.colors.surfaceMuted
                                : theme.colors.surface,
                              borderColor: isSelected
                                ? theme.colors.primary
                                : theme.colors.border,
                              borderRadius: theme.radii.pill,
                              minHeight: 44,
                            },
                          ]}
                        >
                          <Ionicons
                            name={cat.icon as any}
                            size={16}
                            color={isSelected ? theme.colors.primary : theme.colors.textSecondary}
                          />
                          <AppText
                            variant="caption"
                            color={isSelected ? 'textPrimary' : 'textSecondary'}
                          >
                            {cat.name}
                          </AppText>
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                )}
              </View>
            ) : null}

            {/* ── Limit Input ────────────────────────────────────────── */}
            <View style={{ gap: theme.spacing.xs }}>
              <AppText variant="bodyStrong" color="textPrimary">
                Spending Limit (₹)
              </AppText>
              <AppInput
                label="Spending Limit"
                placeholder="e.g. 5000"
                keyboardType="numeric"
                value={limitRupees}
                onChangeText={setLimitRupees}
                accessibilityLabel="Enter budget limit in rupees"
              />
              <AppText variant="caption" color="textSecondary">
                We will alert you when you reach 80% and 100% of this limit.
              </AppText>
            </View>

            {/* ── Error Banner ───────────────────────────────────────── */}
            {error && (
              <View
                style={[
                  styles.errorBanner,
                  {
                    backgroundColor: theme.colors.negative.soft,
                    borderColor: theme.colors.negative.text,
                    borderRadius: theme.radii.md,
                    padding: theme.spacing.sm,
                  },
                ]}
              >
                <AppText variant="body" color="negative">
                  {error}
                </AppText>
              </View>
            )}

            {/* ── Submit / Cancel Buttons ────────────────────────────── */}
            <View style={[styles.btnRow, { gap: theme.spacing.sm, marginTop: theme.spacing.sm }]}>
              <View style={styles.flex1}>
                <Button
                  label="Cancel"
                  variant="outline"
                  onPress={onClose}
                  disabled={isSubmitting}
                  accessibilityLabel="Cancel budget form"
                />
              </View>
              <View style={styles.flex1}>
                <Button
                  label={isSubmitting ? 'Saving...' : isEditing ? 'Save Changes' : 'Create Budget'}
                  variant="primary"
                  onPress={handleSubmit}
                  loading={isSubmitting}
                  disabled={isSubmitting}
                  accessibilityLabel={isEditing ? 'Save budget limit' : 'Submit new budget'}
                />
              </View>
            </View>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalContent: {
    maxHeight: '90%',
    width: '100%',
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  closeBtn: {
    padding: 4,
  },
  segmentRow: {
    flexDirection: 'row',
    padding: 4,
  },
  segmentBtn: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
  },
  categoryChipsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderWidth: 1,
    gap: 6,
  },
  errorBanner: {
    borderWidth: 1,
  },
  btnRow: {
    flexDirection: 'row',
  },
  flex1: {
    flex: 1,
  },
});
