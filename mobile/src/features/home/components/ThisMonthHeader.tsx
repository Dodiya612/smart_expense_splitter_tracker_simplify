import React from 'react';
import { StyleSheet, View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { formatPaiseToInr } from '../utils/dashboardSummary';

export interface ThisMonthHeaderProps {
  monthLabel: string;
  totalSpentPaise: number;
  /** Optional element shown at the end of the title row (the notification bell). */
  trailing?: React.ReactNode;
}

export function ThisMonthHeader({ monthLabel, totalSpentPaise, trailing }: ThisMonthHeaderProps) {
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
        <View style={[styles.trailingRow, { gap: theme.spacing.sm }]}>
          <AppText variant="small" color="textSecondary">
            {monthLabel}
          </AppText>
          {trailing}
        </View>
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
  trailingRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  amountContainer: {
    gap: 2,
  },
  moneyLarge: {
    letterSpacing: -0.5,
  },
});
