/**
 * BudgetsScreen Component (T-49 / US-25).
 *
 * Full screen for Budgets:
 * - Header with title & Add button
 * - Filter tabs (All, Monthly, Weekly)
 * - List of Budget cards
 * - Pull to refresh & loading indicator
 * - Error banner with Retry
 * - Empty state with Create action
 * - Confirm delete dialog
 * - Create / Edit modal form
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { useTheme } from '@/theme';
import { BudgetCard } from '../components/BudgetCard';
import { BudgetEmptyState } from '../components/BudgetEmptyState';
import { BudgetFormModal } from '../components/BudgetFormModal';
import { BudgetRecommendationCard } from '../components/BudgetRecommendationCard';
import { useBudgets } from '../hooks/useBudgets';
import {
  budgetsApi,
  type BudgetRecommendation,
  type SavingsLevelPercent,
} from '../services/budgetsApi';
import type { Budget, BudgetPeriod } from '../types';
import { getCategoryMeta } from '../utils/categories';

export function BudgetsScreen() {
  const theme = useTheme();
  const router = useRouter();

  const {
    budgets,
    isLoading,
    isRefreshing,
    isSubmitting,
    error,
    refresh,
    retry,
    createBudget,
    updateBudget,
    deleteBudget,
  } = useBudgets();

  // Tab filter: 'all' | 'monthly' | 'weekly'
  const [filterPeriod, setFilterPeriod] = useState<'all' | BudgetPeriod>('all');

  // Modal & Dialog state
  const [isFormModalVisible, setIsFormModalVisible] = useState(false);
  const [budgetToEdit, setBudgetToEdit] = useState<Budget | null>(null);
  const [budgetToDelete, setBudgetToDelete] = useState<Budget | null>(null);

  // AI Goal Setting state (T-55 / US-25)
  const [recSavingsLevel, setRecSavingsLevel] = useState<SavingsLevelPercent>(10);
  const [recCategoryId, setRecCategoryId] = useState<string | null>(null);
  const [recommendation, setRecommendation] = useState<BudgetRecommendation | null>(null);
  const [isRecLoading, setIsRecLoading] = useState(false);
  const [recError, setRecError] = useState<string | null>(null);

  const fetchRecommendation = useCallback(
    async (level: SavingsLevelPercent, catId: string | null) => {
      setIsRecLoading(true);
      setRecError(null);
      try {
        const rec = await budgetsApi.getBudgetRecommendation({
          savingsLevelPercent: level,
          categoryId: catId,
        });
        setRecommendation(rec);
      } catch (err) {
        setRecError(err instanceof Error ? err.message : 'Failed to load recommendation');
      } finally {
        setIsRecLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    fetchRecommendation(recSavingsLevel, recCategoryId);
  }, [fetchRecommendation, recSavingsLevel, recCategoryId]);

  const handleRefresh = async () => {
    await Promise.all([
      refresh(),
      fetchRecommendation(recSavingsLevel, recCategoryId),
    ]);
  };

  // Filtered budgets list
  const filteredBudgets = useMemo(() => {
    if (filterPeriod === 'all') return budgets;
    return budgets.filter((b) => b.period === filterPeriod);
  }, [budgets, filterPeriod]);

  // Open create form
  const handleOpenCreate = () => {
    setBudgetToEdit(null);
    setIsFormModalVisible(true);
  };

  // Open edit form
  const handleOpenEdit = (budget: Budget) => {
    setBudgetToEdit(budget);
    setIsFormModalVisible(true);
  };

  // Apply AI Recommendation: prefills form for confirmation
  const handleApplyRecommendation = (rec: BudgetRecommendation) => {
    const existing = budgets.find(
      (b) => b.period === 'monthly' && (b.categoryId ?? null) === (rec.categoryId ?? null)
    );

    if (existing) {
      setBudgetToEdit({
        ...existing,
        limitPaise: rec.recommendedLimitPaise,
      });
    } else {
      setBudgetToEdit({
        id: 'RECOMMENDED_DRAFT',
        period: 'monthly',
        categoryId: rec.categoryId,
        limitPaise: rec.recommendedLimitPaise,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        progress: {
          periodStart: '',
          periodEnd: '',
          spentPaise: 0,
          remainingPaise: rec.recommendedLimitPaise,
          overByPaise: 0,
          percentUsed: 0,
          status: 'under',
        },
      });
    }
    setIsFormModalVisible(true);
  };

  // Confirm delete handler
  const handleConfirmDelete = async () => {
    if (!budgetToDelete) return;
    try {
      await deleteBudget(budgetToDelete.id);
    } finally {
      setBudgetToDelete(null);
    }
  };

  return (
    <ScreenContainer
      style={[styles.container, { backgroundColor: theme.colors.background }]}
    >
      {/* ── Top Bar / Header ───────────────────────────────────── */}
      <View style={[styles.topBar, { gap: theme.spacing.sm }]}>
        <View style={styles.topBarLeft}>
          <TouchableOpacity
            testID="budgets-back-btn"
            accessibilityRole="button"
            accessibilityLabel="Go back"
            onPress={() => router.back()}
            style={[styles.backBtn, { minHeight: 44, minWidth: 44, justifyContent: 'center' }]}
          >
            <Ionicons name="arrow-back" size={24} color={theme.colors.textPrimary} />
          </TouchableOpacity>
          <AppText variant="title" color="textPrimary">
            Budgets
          </AppText>
        </View>

        <Button
          label="New Budget"
          variant="primary"
          onPress={handleOpenCreate}
          accessibilityLabel="Add new budget"
        />
      </View>

      {/* ── Period Filter Chips ─────────────────────────────────── */}
      <View style={[styles.filterRow, { gap: theme.spacing.xs, paddingHorizontal: theme.spacing.md }]}>
        {(['all', 'monthly', 'weekly'] as const).map((tab) => {
          const isSelected = filterPeriod === tab;
          const label = tab === 'all' ? 'All' : tab === 'monthly' ? 'Monthly' : 'Weekly';
          return (
            <TouchableOpacity
              key={tab}
              testID={`filter-tab-${tab}`}
              accessibilityRole="tab"
              accessibilityState={{ selected: isSelected }}
              accessibilityLabel={`Filter by ${label} budgets`}
              onPress={() => setFilterPeriod(tab)}
              style={[
                styles.filterChip,
                {
                  backgroundColor: isSelected ? theme.colors.surfaceMuted : theme.colors.surface,
                  borderColor: isSelected ? theme.colors.primary : theme.colors.border,
                  borderRadius: theme.radii.pill,
                  minHeight: 44,
                },
              ]}
            >
              <AppText
                variant="bodyStrong"
                color={isSelected ? 'textPrimary' : 'textSecondary'}
              >
                {label}
              </AppText>
            </TouchableOpacity>
          );
        })}
      </View>

      {/* ── Content Area ────────────────────────────────────────── */}
      <ScrollView
        contentContainerStyle={[styles.scrollContent, { padding: theme.spacing.md, gap: theme.spacing.md }]}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={handleRefresh}
            tintColor={theme.colors.primary}
            colors={[theme.colors.primary]}
          />
        }
      >
        {/* Error banner */}
        {error && (
          <AppCard
            style={[
              styles.errorCard,
              {
                backgroundColor: theme.colors.negative.soft,
                borderColor: theme.colors.negative.text,
                gap: theme.spacing.sm,
              },
            ]}
          >
            <View style={styles.errorContent}>
              <Ionicons name="alert-circle-outline" size={20} color={theme.colors.negative.text} />
              <AppText variant="body" color="negative" style={styles.flex1}>
                {error}
              </AppText>
            </View>
            <Button
              label="Retry"
              variant="outline"
              onPress={retry}
              accessibilityLabel="Retry loading budgets"
            />
          </AppCard>
        )}

        {/* AI Recommendation Card (T-55 / US-25) */}
        <BudgetRecommendationCard
          recommendation={recommendation}
          isLoading={isRecLoading}
          error={recError}
          selectedSavingsLevel={recSavingsLevel}
          onChangeSavingsLevel={setRecSavingsLevel}
          selectedCategoryId={recCategoryId}
          onChangeCategory={setRecCategoryId}
          onRetry={() => fetchRecommendation(recSavingsLevel, recCategoryId)}
          onApply={handleApplyRecommendation}
        />

        {/* Loading spinner */}
        {isLoading && !isRefreshing ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={theme.colors.primary} />
            <AppText variant="caption" color="textSecondary">
              Loading your budgets...
            </AppText>
          </View>
        ) : filteredBudgets.length === 0 ? (
          /* Empty state */
          <BudgetEmptyState
            onCreatePress={handleOpenCreate}
            isFiltered={filterPeriod !== 'all' && budgets.length > 0}
            onClearFilter={() => setFilterPeriod('all')}
          />
        ) : (
          /* Budget list */
          filteredBudgets.map((budget) => (
            <BudgetCard
              key={budget.id}
              budget={budget}
              onEdit={handleOpenEdit}
              onDelete={setBudgetToDelete}
              testID={`budget-card-${budget.id}`}
            />
          ))
        )}
      </ScrollView>

      {/* ── Form Modal (Create / Edit) ──────────────────── */}
      <BudgetFormModal
        visible={isFormModalVisible}
        budgetToEdit={budgetToEdit}
        onClose={() => setIsFormModalVisible(false)}
        onSubmitCreate={async (payload) => {
          await createBudget(payload);
        }}
        onSubmitUpdate={async (id, payload) => {
          if (id === 'RECOMMENDED_DRAFT') {
            await createBudget({
              period: 'monthly',
              categoryId: budgetToEdit?.categoryId ?? null,
              limitPaise: payload.limitPaise,
            });
          } else {
            await updateBudget(id, payload);
          }
        }}
        isSubmitting={isSubmitting}
      />

      {/* ── Delete Confirmation Dialog ─────────────────────────── */}
      <ConfirmDialog
        visible={Boolean(budgetToDelete)}
        title="Delete Budget"
        message={
          budgetToDelete
            ? `Are you sure you want to delete this ${budgetToDelete.period} ${
                getCategoryMeta(budgetToDelete.categoryId)?.name || 'overall'
              } budget?`
            : ''
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={handleConfirmDelete}
        onCancel={() => setBudgetToDelete(null)}
      />
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 8,
  },
  topBarLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  backBtn: {
    padding: 4,
  },
  filterRow: {
    flexDirection: 'row',
    paddingVertical: 8,
  },
  filterChip: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderWidth: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  scrollContent: {
    flexGrow: 1,
    paddingBottom: 40,
  },
  loadingContainer: {
    paddingVertical: 40,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  errorCard: {
    borderWidth: 1,
  },
  errorContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  flex1: {
    flex: 1,
  },
});
