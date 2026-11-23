import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import { formatPaise } from '@/utils/money';
import type { RecurringRule, RuleAction } from '../types';
import {
  STATUS_LABELS,
  allowedActions,
  categoryLabel,
  frequencyLabel,
  nextRunText,
} from '../utils/recurring';

export interface RecurringRuleCardProps {
  rule: RecurringRule;
  busy: boolean;
  /** Another rule's action is running; buttons wait. */
  locked: boolean;
  onAction: (rule: RecurringRule, action: RuleAction) => void;
}

const ACTION_LABELS: Record<RuleAction, string> = {
  pause: 'Pause',
  resume: 'Resume',
  cancel: 'Cancel repeat',
};

/** One recurring expense with its schedule, status and actions (T-45 / US-14). */
export function RecurringRuleCard({ rule, busy, locked, onAction }: RecurringRuleCardProps) {
  const theme = useTheme();
  const actions = allowedActions(rule.status);
  const pill =
    rule.status === 'active'
      ? { bg: theme.colors.positive.soft, color: 'positive' as const, icon: 'repeat' as const }
      : rule.status === 'paused'
        ? { bg: theme.colors.warning.soft, color: 'warning' as const, icon: 'pause' as const }
        : { bg: theme.colors.surfaceMuted, color: 'textSecondary' as const, icon: 'close' as const };
  const iconColor =
    rule.status === 'active'
      ? theme.colors.positive.text
      : rule.status === 'paused'
        ? theme.colors.warning.text
        : theme.colors.textSecondary;
  const summary = `${frequencyLabel(rule.frequency)} · ${categoryLabel(rule.categoryId)}`;

  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          borderRadius: theme.radii.lg,
          padding: theme.spacing.lg,
          gap: theme.spacing.sm,
        },
      ]}
      accessibilityLabel={`${rule.description}, ${formatPaise(rule.amountPaise)}, ${summary}, ${STATUS_LABELS[rule.status]}. ${nextRunText(rule)}`}>
      <View style={[styles.row, { gap: theme.spacing.sm }]}>
        <View style={styles.flex}>
          <AppText variant="bodyStrong" numberOfLines={2}>
            {rule.description}
          </AppText>
          <AppText variant="caption" color="textSecondary">
            {summary}
          </AppText>
        </View>
        <AppText variant="money">{formatPaise(rule.amountPaise)}</AppText>
      </View>

      <View style={[styles.row, { gap: theme.spacing.sm }]}>
        <View
          style={[
            styles.pill,
            {
              backgroundColor: pill.bg,
              borderRadius: theme.radii.pill,
              paddingHorizontal: theme.spacing.sm,
              paddingVertical: theme.spacing.xs,
              gap: theme.spacing.xs,
            },
          ]}>
          <Ionicons name={pill.icon} size={12} color={iconColor} />
          <AppText variant="caption" color={pill.color}>
            {STATUS_LABELS[rule.status]}
          </AppText>
        </View>
        <AppText variant="caption" color="textSecondary" style={styles.flex}>
          {nextRunText(rule)}
        </AppText>
      </View>

      {rule.groupId ? (
        <AppText variant="caption" color="textSecondary">
          Group expense
        </AppText>
      ) : null}

      {actions.length > 0 ? (
        <View style={[styles.row, { gap: theme.spacing.sm, marginTop: theme.spacing.xs }]}>
          {actions.map((action) => (
            <Button
              key={action}
              label={ACTION_LABELS[action]}
              variant={action === 'cancel' ? 'destructive' : 'outline'}
              style={styles.flex}
              loading={busy && action !== 'cancel'}
              disabled={busy || locked}
              accessibilityLabel={`${ACTION_LABELS[action]}: ${rule.description}`}
              onPress={() => onAction(rule, action)}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1 },
  row: { flexDirection: 'row', alignItems: 'center' },
  flex: { flex: 1 },
  pill: { flexDirection: 'row', alignItems: 'center' },
});
