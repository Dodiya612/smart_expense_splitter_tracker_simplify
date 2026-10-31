import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { useTheme } from '@/theme';

export function HomeScreen() {
  const theme = useTheme();

  return (
    <ScreenContainer scrollable>
      <View style={[styles.container, { gap: theme.spacing.lg, paddingVertical: theme.spacing.lg }]}>
        <View style={{ gap: theme.spacing.xs }}>
          <AppText variant="title" color="textPrimary">Home</AppText>
          <AppText variant="body" color="textSecondary">Expense tracking overview (Phase 4)</AppText>
        </View>

        {/* Budget Preview Card */}
        <AppCard
          accessibilityLabel="Budget preview, placeholder limit remaining, tap to view full Budgets page"
          accessibilityHint="Navigates to the Budgets page"
          onPress={() => router.push('/budgets' as Href)}
          style={{ gap: theme.spacing.sm }}>
          <View style={styles.cardHeader}>
            <View style={[styles.titleRow, { gap: theme.spacing.xs }]}>
              <Ionicons name="wallet-outline" size={18} color={theme.colors.primary} />
              <AppText variant="bodyStrong" color="textPrimary">Monthly budget</AppText>
            </View>
            <Ionicons name="chevron-forward" size={16} color={theme.colors.textSecondary} />
          </View>

          {/* Progress bar placeholder */}
          <View
            style={[
              styles.progressBarTrack,
              {
                backgroundColor: theme.colors.surfaceMuted,
                borderRadius: theme.radii.pill,
              },
            ]}>
            <View
              style={[
                styles.progressBarFill,
                {
                  backgroundColor: theme.colors.info.fill,
                  borderRadius: theme.radii.pill,
                  width: '60%',
                },
              ]}
            />
          </View>

          <View style={styles.cardFooter}>
            <AppText variant="caption" color="textSecondary">Provisional limit: ₹50,000</AppText>
            <AppText variant="caption" color="positive">+₹20,000 remaining</AppText>
          </View>
        </AppCard>

        {/* Analytics Preview Card */}
        <AppCard
          accessibilityLabel="Analytics preview, category breakdown, tap to view full Analytics page"
          accessibilityHint="Navigates to the Analytics page"
          onPress={() => router.push('/analytics' as Href)}
          style={{ gap: theme.spacing.sm }}>
          <View style={styles.cardHeader}>
            <View style={[styles.titleRow, { gap: theme.spacing.xs }]}>
              <Ionicons name="pie-chart-outline" size={18} color={theme.colors.primary} />
              <AppText variant="bodyStrong" color="textPrimary">Spending insights</AppText>
            </View>
            <Ionicons name="chevron-forward" size={16} color={theme.colors.textSecondary} />
          </View>

          {/* Category distribution preview chips */}
          <View style={[styles.chipsRow, { gap: theme.spacing.xs }]}>
            <View style={[styles.chip, { backgroundColor: theme.categoryPalette[0].soft, borderRadius: theme.radii.sm }]}>
              <AppText variant="caption" color="textPrimary">Food: 40%</AppText>
            </View>
            <View style={[styles.chip, { backgroundColor: theme.categoryPalette[1].soft, borderRadius: theme.radii.sm }]}>
              <AppText variant="caption" color="textPrimary">Rent: 35%</AppText>
            </View>
            <View style={[styles.chip, { backgroundColor: theme.categoryPalette[2].soft, borderRadius: theme.radii.sm }]}>
              <AppText variant="caption" color="textPrimary">Bills: 25%</AppText>
            </View>
          </View>

          <View style={styles.cardFooter}>
            <AppText variant="caption" color="textSecondary">Category distribution breakdown</AppText>
          </View>
        </AppCard>
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  progressBarTrack: {
    width: '100%',
    height: 6,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: 6,
  },
  cardFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  chipsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  chip: {
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
});
