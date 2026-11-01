import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { DashboardSummary } from '../types';
import {
  MOCK_EMPTY_DASHBOARD_DATA,
  MOCK_POPULATED_DASHBOARD_DATA,
} from '../data/mockDashboardData';
import { isDashboardEmpty } from '../utils/dashboardSummary';
import { ThisMonthHeader } from '../components/ThisMonthHeader';
import { BalancePreviewCard } from '../components/BalancePreviewCard';
import { BudgetPreviewCard } from '../components/BudgetPreviewCard';
import { RecentExpensesCard } from '../components/RecentExpensesCard';
import { DashboardEmptyState } from '../components/DashboardEmptyState';

export interface HomeScreenProps {
  initialData?: DashboardSummary;
}

export function HomeScreen({ initialData }: HomeScreenProps = {}) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ previewMode?: 'empty' | 'populated' }>();

  // Determine active dataset: prop overrides param, param overrides default populated mock
  const data = useMemo<DashboardSummary>(() => {
    if (initialData) return initialData;
    if (params.previewMode === 'empty') return MOCK_EMPTY_DASHBOARD_DATA;
    return MOCK_POPULATED_DASHBOARD_DATA;
  }, [initialData, params.previewMode]);

  const isEmpty = isDashboardEmpty(data);

  return (
    <ScreenContainer
      scrollable
      contentContainerStyle={[
        styles.scrollContent,
        {
          paddingBottom: Math.max(insets.bottom, theme.spacing.md) + 88,
          gap: theme.spacing.lg,
        },
      ]}
    >
      <View style={[styles.container, { gap: theme.spacing.lg }]}>
        {/* A. Dynamic This-Month Header */}
        <ThisMonthHeader
          monthLabel={data.monthLabel}
          totalSpentPaise={data.totalSpentPaise}
        />

        {/* Dashboard-level demo notice when populated */}
        {!isEmpty && (
          <View
            accessibilityRole="alert"
            accessibilityLabel="Demo data notice: these figures are examples, not your actual expenses."
            style={[
              styles.demoNotice,
              {
                backgroundColor: theme.colors.surfaceMuted,
                borderColor: theme.colors.border,
                borderRadius: theme.radii.md,
                paddingHorizontal: theme.spacing.md,
                paddingVertical: theme.spacing.sm,
                gap: 4,
              },
            ]}
          >
            <View style={[styles.demoNoticeHeader, { gap: theme.spacing.xs }]}>
              <Ionicons name="information-circle-outline" size={16} color={theme.colors.info.text} />
              <AppText
                variant="caption"
                color="textPrimary"
                style={{ fontFamily: theme.fontFamily.semibold }}
              >
                Demo data
              </AppText>
            </View>
            <AppText variant="caption" color="textSecondary">
              These figures are examples, not your actual expenses, budgets, or balances.
            </AppText>
          </View>
        )}

        {/* B. Balances Preview Card (Presentational) */}
        <BalancePreviewCard balances={data.balances} />

        {/* C. Monthly Budget Preview Card (Presentational) */}
        <BudgetPreviewCard budget={data.budget} />

        {/* D / E. Recent Expenses (when populated) OR Meaningful Empty State */}
        {isEmpty ? (
          <DashboardEmptyState />
        ) : (
          <RecentExpensesCard expenses={data.recentExpenses} />
        )}
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  scrollContent: {
    paddingTop: 16,
  },
  container: {
    flex: 1,
    width: '100%',
  },
  demoNotice: {
    width: '100%',
    borderWidth: 1,
  },
  demoNoticeHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
});
