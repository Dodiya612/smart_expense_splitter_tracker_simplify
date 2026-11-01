import React from 'react';
import { StyleSheet, View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { formatPaiseToInr } from '../utils/dashboardSummary';

export interface ThisMonthHeaderProps {
  monthLabel: string;
  totalSpentPaise: number;
}

export function ThisMonthHeader({ monthLabel, totalSpentPaise }: ThisMonthHeaderProps) {
  const theme = useTheme();
  const formattedTotal = formatPaiseToInr(totalSpentPaise);

  return (
    <View
      accessibilityRole="header"
      accessibilityLabel={`Monthly summary for ${monthLabel}. Total spending is ${formattedTotal}`}
      style={[styles.container, { gap: theme.spacing.xs }]}
    >
      <View style={styles.titleRow}>
        <AppText variant="title" color="textPrimary">
          This Month
        </AppText>
        <AppText variant="small" color="textSecondary">
          {monthLabel}
        </AppText>
      </View>

      <View style={[styles.amountContainer, { marginTop: theme.spacing.xs }]}>
        <AppText variant="caption" color="textSecondary">
          Total tracked spending
        </AppText>
        <AppText variant="moneyLarge" color="textPrimary" style={styles.moneyLarge}>
          {formattedTotal}
        </AppText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    width: '100%',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 8,
  },
  amountContainer: {
    gap: 2,
  },
  moneyLarge: {
    letterSpacing: -0.5,
  },
});
