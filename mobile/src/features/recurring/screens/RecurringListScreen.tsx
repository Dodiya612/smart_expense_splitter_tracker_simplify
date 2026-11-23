/**
 * Recurring expenses (T-45 / US-14): every repeat I set up, with its next date,
 * and Pause / Resume / Cancel. Repeats are created from the add-expense form
 * ("Repeat this expense"); the server adds each one on its date and sends a
 * reminder the day before (T-44).
 */

import React, { useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  View,
} from 'react-native';
import { Href, router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { useTheme } from '@/theme';
import { RecurringRuleCard } from '../components/RecurringRuleCard';
import { useRecurringRules } from '../hooks/useRecurringRules';
import type { RecurringRule, RuleAction } from '../types';
import { cancelConfirmText } from '../utils/recurring';

export function RecurringListScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { rules, isLoading, isRefreshing, error, busyRuleId, actionMessage, refresh, retry, runAction } =
    useRecurringRules();
  const [toCancel, setToCancel] = useState<RecurringRule | null>(null);

  const goBack = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)/expenses' as Href);
  };
  const addExpense = () => router.push('/add-expense' as Href);

  const handleAction = (rule: RecurringRule, action: RuleAction) => {
    if (action === 'cancel') setToCancel(rule);
    else void runAction(rule, action);
  };

  const confirmCancel = async () => {
    if (!toCancel) return;
    await runAction(toCancel, 'cancel');
    setToCancel(null);
  };

  const header = (
    <View style={{ gap: theme.spacing.md, marginBottom: theme.spacing.md }}>
      <View style={[styles.row, { gap: theme.spacing.sm }]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          onPress={goBack}
          style={({ pressed }) => [
            styles.center,
            { minWidth: theme.minTouchTarget, minHeight: theme.minTouchTarget },
            pressed && styles.pressed,
          ]}>
          <Ionicons name="chevron-back" size={24} color={theme.colors.textPrimary} />
        </Pressable>
        <View style={styles.flex}>
          <AppText variant="heading" accessibilityRole="header">
            Recurring expenses
          </AppText>
          <AppText variant="caption" color="textSecondary">
            Added on their date. You get a reminder the day before.
          </AppText>
        </View>
      </View>
      <Button label="Add a repeating expense" variant="outline" fullWidth onPress={addExpense} />
      {actionMessage ? (
        <View
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
          style={{
            backgroundColor:
              actionMessage.kind === 'success' ? theme.colors.positive.soft : theme.colors.negative.soft,
            borderRadius: theme.radii.md,
            padding: theme.spacing.md,
          }}>
          <AppText variant="small" color={actionMessage.kind === 'success' ? 'positive' : 'negative'}>
            {actionMessage.kind === 'success' ? actionMessage.text : `[!] ${actionMessage.text}`}
          </AppText>
        </View>
      ) : null}
    </View>
  );

  const padding = {
    paddingTop: insets.top + theme.spacing.md,
    paddingHorizontal: theme.spacing.lg,
  };

  let body: React.ReactElement | null = null;
  if (isLoading && !rules) {
    body = (
      <View style={[styles.state, { gap: theme.spacing.sm }]} accessibilityLiveRegion="polite">
        <ActivityIndicator size="large" color={theme.colors.primary} />
        <AppText variant="body" color="textSecondary">
          Loading your recurring expenses
        </AppText>
      </View>
    );
  } else if (error && !rules) {
    body = (
      <View style={[styles.state, { gap: theme.spacing.sm }]} accessibilityRole="alert">
        <Ionicons name="alert-circle-outline" size={48} color={theme.colors.negative.text} />
        <AppText variant="heading" style={styles.textCenter}>
          Could not load your recurring expenses
        </AppText>
        <AppText variant="body" color="textSecondary" style={styles.textCenter}>
          {error.message}
        </AppText>
        <Button label="Try again" fullWidth onPress={retry} style={{ marginTop: theme.spacing.md }} />
      </View>
    );
  }

  if (body) {
    return (
      <View style={[styles.root, padding, { backgroundColor: theme.colors.background }]}>
        {header}
        {body}
      </View>
    );
  }

  const cancelText = toCancel ? cancelConfirmText(toCancel) : null;

  return (
    <>
      <FlatList
        style={[styles.root, { backgroundColor: theme.colors.background }]}
        contentContainerStyle={[
          styles.content,
          padding,
          { paddingBottom: insets.bottom + theme.spacing.xxxl, gap: theme.spacing.md },
        ]}
        data={rules ?? []}
        keyExtractor={(r) => r.id}
        renderItem={({ item }) => (
          <RecurringRuleCard
            rule={item}
            busy={busyRuleId === item.id}
            locked={busyRuleId !== null && busyRuleId !== item.id}
            onAction={handleAction}
          />
        )}
        ListHeaderComponent={header}
        ListEmptyComponent={
          <View style={[styles.state, { gap: theme.spacing.sm }]}>
            <Ionicons name="repeat" size={48} color={theme.colors.textSecondary} />
            <AppText variant="heading" style={styles.textCenter}>
              No recurring expenses yet
            </AppText>
            <AppText variant="body" color="textSecondary" style={styles.textCenter}>
              {'Add an expense and turn on "Repeat this expense" for rent, subscriptions or recharges.'}
            </AppText>
          </View>
        }
        refreshControl={
          <RefreshControl refreshing={isRefreshing} onRefresh={refresh} tintColor={theme.colors.primary} />
        }
        accessibilityLabel="Your recurring expenses"
      />
      <ConfirmDialog
        visible={toCancel !== null}
        title={cancelText?.title ?? ''}
        message={cancelText?.message ?? ''}
        confirmLabel="Cancel repeat"
        cancelLabel="Keep it"
        onConfirm={confirmCancel}
        onCancel={() => setToCancel(null)}
        isLoading={toCancel !== null && busyRuleId === toCancel.id}
      />
    </>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { flexGrow: 1 },
  row: { flexDirection: 'row', alignItems: 'center' },
  flex: { flex: 1 },
  center: { alignItems: 'center', justifyContent: 'center' },
  pressed: { opacity: 0.6 },
  state: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 48 },
  textCenter: { textAlign: 'center' },
});
