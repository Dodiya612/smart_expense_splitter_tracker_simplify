/**
 * ExpenseHistoryScreen – US-13: Recent Expenses (Paginated Transaction History)
 *
 * Provides a production-grade, paginated transaction history screen with:
 *   - Offset-based infinite scroll pagination via useExpenses({ limit: 20 })
 *   - Pull-to-refresh
 *   - Search (by notes/description/merchant) and category filters using real API parameters
 *   - Initial loading and load-more indicators
 *   - Initial error and pagination retry states
 *   - Distinct empty state and filtered no-results state
 *   - Tap to view Expense Detail View (/expense-detail)
 *   - Full T-20 delete-with-confirm and 10-second undo toast integration
 */

import React, { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { UndoToast } from '@/components/ui/UndoToast';
import { useTheme } from '@/theme';
import { CATEGORIES, type Expense } from '../types';
import { useExpenses } from '../hooks/useExpenses';
import { useDeleteExpense } from '../hooks/useDeleteExpense';
import { ExpenseListItem } from '../components/ExpenseListItem';

export interface ExpenseHistoryScreenProps {
  initialCategoryId?: string;
  onSelectExpense?: (expense: Expense) => void;
}

export function ExpenseHistoryScreen({
  initialCategoryId,
  onSelectExpense,
}: ExpenseHistoryScreenProps = {}) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  const urlParams = useLocalSearchParams<{ q?: string; categoryId?: string }>();

  // ── Filters State (Reflected in URL – US-15) ────────────────────────────────
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(
    urlParams.categoryId ?? initialCategoryId ?? null
  );
  const [searchQuery, setSearchQuery] = useState(urlParams.q ?? '');

  // ── Data Hook ───────────────────────────────────────────────────────────────
  const {
    expenses,
    isLoading,
    isRefreshing,
    isLoadingMore,
    error,
    hasMore,
    total,
    loadMore,
    refresh,
    retry,
  } = useExpenses({
    limit: 20,
    categoryId: selectedCategoryId || undefined,
    query: searchQuery.trim() || undefined,
  });

  // ── Local Deletion / Undo Overlay (US-08) ───────────────────────────────────
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());
  const [restoredItems, setRestoredItems] = useState<Expense[]>([]);

  const displayedExpenses = useMemo(() => {
    // Combine restored items with backend items excluding deletedIds
    const filteredBase = expenses.filter((e) => !deletedIds.has(e.id));
    const combined = [...restoredItems, ...filteredBase];

    // Deduplicate by ID
    const seen = new Set<string>();
    return combined.filter((item) => {
      if (seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
  }, [expenses, deletedIds, restoredItems]);

  // ── T-20 Deletion Hook ──────────────────────────────────────────────────────
  const {
    pendingExpense,
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
    onDeleted: (id) => {
      // Remove immediately from displayed view
      setDeletedIds((prev) => new Set(prev).add(id));
      setRestoredItems((prev) => prev.filter((item) => item.id !== id));
    },
    onRestored: (restored) => {
      // Re-insert into view
      setDeletedIds((prev) => {
        const next = new Set(prev);
        next.delete(restored.id);
        return next;
      });
      setRestoredItems((prev) => [restored, ...prev.filter((e) => e.id !== restored.id)]);
    },
  });

  // ── Navigation Handlers ─────────────────────────────────────────────────────
  const handleItemPress = useCallback(
    (item: Expense) => {
      if (onSelectExpense) {
        onSelectExpense(item);
        return;
      }
      router.push({
        pathname: '/expense-detail',
        params: { expense: JSON.stringify(item) },
      });
    },
    [onSelectExpense]
  );

  const handleAddPress = useCallback(() => {
    router.push('/add-expense');
  }, []);

  const handleCategoryPress = useCallback((categoryId: string | null) => {
    setSelectedCategoryId(categoryId);
    router.setParams({ categoryId: categoryId || undefined });
  }, []);

  const handleSearchChange = useCallback((text: string) => {
    setSearchQuery(text);
    router.setParams({ q: text.trim() || undefined });
  }, []);

  const handleClearFilters = useCallback(() => {
    setSelectedCategoryId(null);
    setSearchQuery('');
    router.setParams({ q: undefined, categoryId: undefined });
  }, []);

  const isFiltered = Boolean(selectedCategoryId || searchQuery.trim());

  // ── Render Header Component ─────────────────────────────────────────────────
  const renderHeader = () => (
    <View style={[styles.headerContainer, { gap: theme.spacing.md, paddingBottom: theme.spacing.sm }]}>
      {/* Top Title Bar */}
      <View style={styles.titleRow}>
        <View style={{ flex: 1 }}>
          <AppText variant="heading" color="textPrimary">
            Transaction History
          </AppText>
          <AppText variant="caption" color="textSecondary">
            {total > 0
              ? `${total} recorded ${total === 1 ? 'expense' : 'expenses'}`
              : 'Browse and track your expenses'}
          </AppText>
        </View>

        <Button
          label="+ Add"
          variant="primary"
          onPress={handleAddPress}
          accessibilityLabel="Add new expense"
        />
      </View>

      {/* Search Input */}
      <AppInput
        label="Search transactions"
        placeholder="Search description, notes or merchant..."
        value={searchQuery}
        onChangeText={handleSearchChange}
        accessibilityLabel="Search transactions"
      />

      {/* Category Filter Chips Horizontal Scroll */}
      <View style={styles.filterSection}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={[styles.categoryScroll, { gap: theme.spacing.xs }]}
        >
          {/* 'All' Chip */}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Filter by all categories"
            accessibilityState={{ selected: selectedCategoryId === null }}
            onPress={() => handleCategoryPress(null)}
            style={({ pressed }) => [
              styles.filterChip,
              {
                minHeight: theme.minTouchTarget,
                borderRadius: theme.radii.pill,
                paddingHorizontal: theme.spacing.md,
                paddingVertical: theme.spacing.xs,
                backgroundColor:
                  selectedCategoryId === null
                    ? theme.colors.primary
                    : theme.colors.surfaceMuted,
                borderColor:
                  selectedCategoryId === null
                    ? theme.colors.primary
                    : theme.colors.border,
              },
              pressed && styles.pressed,
            ]}
          >
            <AppText
              variant="caption"
              color={selectedCategoryId === null ? 'textOnPrimary' : 'textPrimary'}
              style={{ fontFamily: theme.fontFamily.semibold }}
            >
              All
            </AppText>
          </Pressable>

          {/* Individual Category Chips */}
          {CATEGORIES.map((cat) => {
            const isSelected = selectedCategoryId === cat.id;
            const palette = theme.categoryPalette[cat.paletteIndex];

            return (
              <Pressable
                key={cat.id}
                accessibilityRole="button"
                accessibilityLabel={`Filter by ${cat.label}`}
                accessibilityState={{ selected: isSelected }}
                onPress={() => handleCategoryPress(isSelected ? null : cat.id)}
                style={({ pressed }) => [
                  styles.filterChip,
                  {
                    minHeight: theme.minTouchTarget,
                    borderRadius: theme.radii.pill,
                    paddingHorizontal: theme.spacing.md,
                    paddingVertical: theme.spacing.xs,
                    backgroundColor: isSelected ? palette.soft : theme.colors.surfaceMuted,
                    borderColor: isSelected ? palette.fill : theme.colors.border,
                  },
                  pressed && styles.pressed,
                ]}
              >
                <AppText
                  variant="caption"
                  style={{
                    color: isSelected ? palette.fill : theme.colors.textPrimary,
                    fontFamily: theme.fontFamily.semibold,
                  }}
                >
                  {cat.label}
                </AppText>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      {/* Delete Error Banner */}
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
    </View>
  );

  // ── Render Footer Component (Load More & Pagination States) ─────────────────
  const renderFooter = () => {
    if (isLoadingMore) {
      return (
        <View style={[styles.footerContainer, { paddingVertical: theme.spacing.lg, gap: theme.spacing.xs }]}>
          <ActivityIndicator size="small" color={theme.colors.primary} />
          <AppText variant="caption" color="textSecondary">
            Loading more expenses...
          </AppText>
        </View>
      );
    }

    if (error && displayedExpenses.length > 0) {
      return (
        <View style={[styles.footerContainer, { paddingVertical: theme.spacing.md, gap: theme.spacing.sm }]}>
          <AppText variant="caption" color="negative">
            Could not load more items: {error.message}
          </AppText>
          <Button
            label="Retry loading more"
            variant="outline"
            onPress={retry}
            accessibilityLabel="Retry loading more expenses"
          />
        </View>
      );
    }

    if (!hasMore && displayedExpenses.length > 0) {
      return (
        <View style={[styles.footerContainer, { paddingVertical: theme.spacing.lg }]}>
          <AppText variant="caption" color="textSecondary">
            {`All transactions loaded (${displayedExpenses.length} total)`}
          </AppText>
        </View>
      );
    }

    return null;
  };

  // ── Render Empty / No-Results / Initial Error States ────────────────────────
  const renderEmptyComponent = () => {
    // Initial loading indicator
    if (isLoading && displayedExpenses.length === 0) {
      return (
        <View style={[styles.centerBlock, { paddingVertical: theme.spacing.xxxl * 2, gap: theme.spacing.md }]}>
          <ActivityIndicator size="large" color={theme.colors.primary} />
          <AppText variant="body" color="textSecondary">
            Loading transactions...
          </AppText>
        </View>
      );
    }

    // Initial full-page error with retry
    if (error && displayedExpenses.length === 0) {
      return (
        <AppCard
          style={[
            styles.centerBlock,
            {
              padding: theme.spacing.xl,
              gap: theme.spacing.md,
              marginTop: theme.spacing.lg,
            },
          ]}
        >
          <View
            style={[
              styles.iconCircle,
              {
                backgroundColor: theme.colors.negative.soft,
                borderRadius: theme.radii.pill,
              },
            ]}
          >
            <Ionicons name="alert-circle-outline" size={32} color={theme.colors.negative.text} />
          </View>
          <AppText variant="heading" color="textPrimary" style={styles.centerText}>
            Could not load expenses
          </AppText>
          <AppText variant="body" color="textSecondary" style={styles.centerText}>
            {error.message || 'A network error occurred. Please check your connection and try again.'}
          </AppText>
          <Button
            label="Retry"
            variant="primary"
            fullWidth
            onPress={retry}
            accessibilityLabel="Retry loading expenses"
          />
        </AppCard>
      );
    }

    // Filtered No-Results State
    if (isFiltered) {
      return (
        <AppCard
          style={[
            styles.centerBlock,
            {
              padding: theme.spacing.xl,
              gap: theme.spacing.md,
              marginTop: theme.spacing.lg,
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
            <Ionicons name="search-outline" size={32} color={theme.colors.textSecondary} />
          </View>
          <AppText variant="heading" color="textPrimary" style={styles.centerText}>
            No matching expenses
          </AppText>
          <AppText variant="body" color="textSecondary" style={styles.centerText}>
            No transactions match your current search or category filter.
          </AppText>
          <Button
            label="Clear filters"
            variant="outline"
            fullWidth
            onPress={handleClearFilters}
            accessibilityLabel="Clear filters and search"
          />
        </AppCard>
      );
    }

    // Meaningful Empty State (0 expenses recorded)
    return (
      <AppCard
        style={[
          styles.centerBlock,
          {
            padding: theme.spacing.xl,
            gap: theme.spacing.md,
            marginTop: theme.spacing.lg,
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
        <AppText variant="heading" color="textPrimary" style={styles.centerText}>
          No expenses recorded yet
        </AppText>
        <AppText variant="body" color="textSecondary" style={styles.centerText}>
          Transactions you add will appear here with full history, pagination, and details.
        </AppText>
        <Button
          label="+ Add Your First Expense"
          variant="primary"
          fullWidth
          onPress={handleAddPress}
          accessibilityLabel="Add your first expense"
        />
      </AppCard>
    );
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <FlatList
        data={displayedExpenses}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <ExpenseListItem
            expense={item}
            onPress={handleItemPress}
            onEdit={handleItemPress}
            onDelete={requestDelete}
          />
        )}
        ListHeaderComponent={renderHeader}
        ListFooterComponent={renderFooter}
        ListEmptyComponent={renderEmptyComponent}
        onEndReached={() => {
          if (hasMore && !isLoadingMore && !isLoading) {
            void loadMore();
          }
        }}
        onEndReachedThreshold={0.4}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={refresh}
            tintColor={theme.colors.primary}
          />
        }
        contentContainerStyle={[
          styles.listContent,
          {
            paddingHorizontal: theme.spacing.lg,
            paddingTop: insets.top + theme.spacing.md,
            paddingBottom: insets.bottom + theme.spacing.xxxl,
            gap: theme.spacing.md,
          },
        ]}
        showsVerticalScrollIndicator={false}
        accessibilityRole="list"
        accessibilityLabel="Paginated transaction history"
      />

      {/* ── T-20: Confirm delete dialog (US-08) ─────────────────── */}
      <ConfirmDialog
        visible={confirmDialogVisible}
        title="Delete expense?"
        message={
          pendingExpense
            ? `Delete ₹${(pendingExpense.amountPaise / 100).toFixed(2)} on ${pendingExpense.date}? You'll have 10 seconds to undo.`
            : 'Are you sure you want to delete this expense?'
        }
        confirmLabel="Delete"
        cancelLabel="Keep it"
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        isLoading={isDeleting}
      />

      {/* ── T-20: 10-second undo toast (US-08) ──────────────────── */}
      <UndoToast
        visible={toastVisible}
        message="Expense deleted"
        durationMs={10_000}
        onUndo={handleUndo}
        onDismissed={handleToastDismissed}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  listContent: {
    flexGrow: 1,
  },
  headerContainer: {
    width: '100%',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  filterSection: {
    width: '100%',
  },
  categoryScroll: {
    paddingVertical: 4,
    alignItems: 'center',
  },
  filterChip: {
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  footerContainer: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
  },
  centerBlock: {
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
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
  banner: {
    borderWidth: 1,
    width: '100%',
  },
  pressed: {
    opacity: 0.85,
  },
});