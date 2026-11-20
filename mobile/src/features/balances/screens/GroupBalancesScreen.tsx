/**
 * GroupBalancesScreen component (T-33 / US-10).
 *
 * - Headline from the current user's net position: "You owe ₹X", "You are owed ₹X" or "Settled up".
 * - Per-person rows from the ledger's simplified repayments ("Y owes you ₹X" / "You owe Y ₹X").
 * - Settle sheet for full or partial settlements; balances and the settlement list refresh after saving.
 * - Loading, empty ("No balances yet"), error with Retry, and success states.
 * Reached from a group's screen (Groups tab → group → Balances), with ?groupId=…
 */

import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/features/auth/context/AuthContext';
import { useTheme } from '@/theme';
import { formatPaise } from '@/utils/money';
import { MemberBalanceCard } from '../components/MemberBalanceCard';
import { NetPositionCard } from '../components/NetPositionCard';
import { SettlementHistoryRow } from '../components/SettlementHistoryRow';
import { SettleUpModal } from '../components/SettleUpModal';
import { useGroupBalances } from '../hooks/useGroupBalances';
import type { PeerStanding, SettlementRecord } from '../types';

export interface GroupBalancesScreenProps {
  groupId?: string;
  groupName?: string;
}

type Row =
  | { type: 'header'; title: string; count: number }
  | { type: 'item'; standing: PeerStanding }
  | { type: 'settlement'; record: SettlementRecord }
  | { type: 'empty'; message: string };

export function GroupBalancesScreen({ groupId: propGroupId, groupName: propGroupName }: GroupBalancesScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const params = useLocalSearchParams<{ groupId?: string; groupName?: string }>();

  const activeGroupId = propGroupId || params.groupId || undefined;
  const displayGroupName = propGroupName || params.groupName || 'Group balances';

  const {
    group,
    settlements,
    isLoading,
    isRefreshing,
    error,
    isEmpty,
    userNetBalancePaise,
    userYouAreOwedPaise,
    userYouOwePaise,
    peopleWhoOweYou,
    peopleYouOwe,
    settledMembers,
    nameOf,
    refresh,
    retry,
    submitSettlement,
    balances,
  } = useGroupBalances({ groupId: activeGroupId });

  const [selectedCounterparty, setSelectedCounterparty] = useState<PeerStanding | null>(null);
  const [successToast, setSuccessToast] = useState<string | null>(null);

  useEffect(() => {
    if (!successToast) return;
    const timer = setTimeout(() => setSuccessToast(null), 4000);
    return () => clearTimeout(timer);
  }, [successToast]);

  const rows = useMemo(() => {
    const list: Row[] = [];
    list.push({ type: 'header', title: 'People who owe you', count: peopleWhoOweYou.length });
    if (peopleWhoOweYou.length > 0) {
      for (const standing of peopleWhoOweYou) list.push({ type: 'item', standing });
    } else {
      list.push({ type: 'empty', message: 'Nobody owes you money in this group.' });
    }

    list.push({ type: 'header', title: 'People you owe', count: peopleYouOwe.length });
    if (peopleYouOwe.length > 0) {
      for (const standing of peopleYouOwe) list.push({ type: 'item', standing });
    } else {
      list.push({ type: 'empty', message: 'You do not owe anyone in this group.' });
    }

    if (settledMembers.length > 0) {
      list.push({ type: 'header', title: 'Settled up', count: settledMembers.length });
      for (const standing of settledMembers) list.push({ type: 'item', standing });
    }

    if (settlements.length > 0) {
      list.push({ type: 'header', title: 'Recorded settlements', count: settlements.length });
      for (const record of settlements) list.push({ type: 'settlement', record });
    }
    return list;
  }, [peopleWhoOweYou, peopleYouOwe, settledMembers, settlements]);

  const handleSaved = (saved: SettlementRecord) => {
    setSuccessToast(`Settlement of ${formatPaise(saved.amountPaise)} recorded.`);
  };

  if (isLoading && !balances) {
    return (
      <View
        style={[styles.center, { backgroundColor: theme.colors.background }]}
        accessibilityLabel="Loading group balances"
      >
        <ActivityIndicator size="large" color={theme.colors.primary} />
        <AppText variant="body" color="textSecondary" style={{ marginTop: theme.spacing.md }}>
          Loading balances…
        </AppText>
      </View>
    );
  }

  if (error && !balances) {
    return (
      <View
        style={[styles.center, { backgroundColor: theme.colors.background, padding: theme.spacing.xl }]}
        accessibilityRole="alert"
      >
        <Ionicons name="alert-circle-outline" size={48} color={theme.colors.negative.text} />
        <AppText variant="heading" color="textPrimary" style={[styles.centerText, { marginTop: theme.spacing.md }]}>
          Could not load balances
        </AppText>
        <AppText variant="body" color="textSecondary" style={[styles.centerText, { marginTop: theme.spacing.xs }]}>
          {error.message}
        </AppText>
        {activeGroupId ? (
          <View style={[styles.fullWidth, { marginTop: theme.spacing.lg }]}>
            <Button label="Try again" variant="primary" fullWidth onPress={() => void retry()} />
          </View>
        ) : null}
      </View>
    );
  }

  const header = (
    <View style={[styles.fullWidth, { gap: theme.spacing.md, paddingBottom: theme.spacing.sm }]}>
      <View>
        <AppText variant="heading" color="textPrimary">
          {group?.name || displayGroupName}
        </AppText>
        <AppText variant="caption" color="textSecondary">
          Balances and settlements
        </AppText>
      </View>

      {isEmpty ? (
        <AppCard style={[styles.bordered, { borderColor: theme.colors.border, gap: theme.spacing.xs }]}>
          <AppText variant="bodyStrong" color="textPrimary">
            No balances yet
          </AppText>
          <AppText variant="caption" color="textSecondary">
            Add a group expense to see who owes whom.
          </AppText>
        </AppCard>
      ) : (
        <NetPositionCard
          netBalancePaise={userNetBalancePaise}
          youAreOwedPaise={userYouAreOwedPaise}
          youOwePaise={userYouOwePaise}
        />
      )}

      {successToast ? (
        <View
          style={[
            styles.row,
            styles.bordered,
            {
              gap: theme.spacing.xs,
              backgroundColor: theme.colors.positive.soft,
              borderColor: theme.colors.positive.fill,
              borderRadius: theme.radii.sm,
              padding: theme.spacing.sm,
            },
          ]}
          accessibilityRole="alert"
        >
          <Ionicons name="checkmark-circle" size={16} color={theme.colors.positive.text} />
          <AppText variant="small" style={{ color: theme.colors.positive.text, flex: 1 }}>
            {successToast}
          </AppText>
        </View>
      ) : null}
    </View>
  );

  const renderRow = ({ item }: { item: Row }) => {
    if (item.type === 'header') {
      return (
        <View style={{ marginTop: theme.spacing.md, marginBottom: theme.spacing.xs }}>
          <AppText variant="bodyStrong" color="textPrimary">
            {`${item.title} (${item.count})`}
          </AppText>
        </View>
      );
    }
    if (item.type === 'empty') {
      return (
        <View
          style={[
            styles.bordered,
            {
              backgroundColor: theme.colors.surfaceMuted,
              borderRadius: theme.radii.sm,
              borderColor: theme.colors.border,
              padding: theme.spacing.sm,
              marginBottom: theme.spacing.xs,
            },
          ]}
        >
          <AppText variant="caption" color="textSecondary">
            {item.message}
          </AppText>
        </View>
      );
    }
    if (item.type === 'settlement') {
      return (
        <View style={{ marginBottom: theme.spacing.xs }}>
          <SettlementHistoryRow record={item.record} currentUserId={user?.id} nameOf={nameOf} />
        </View>
      );
    }
    return (
      <View style={{ marginBottom: theme.spacing.xs }}>
        <MemberBalanceCard
          standing={item.standing}
          onSettlePress={setSelectedCounterparty}
          canSettle={item.standing.status !== 'settled'}
        />
      </View>
    );
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <FlatList
        data={isEmpty ? [] : rows}
        keyExtractor={(item, index) => {
          if (item.type === 'item') return `member-${item.standing.userId}`;
          if (item.type === 'settlement') return `settlement-${item.record.id}`;
          return `${item.type}-${index}`;
        }}
        ListHeaderComponent={header}
        renderItem={renderRow}
        refreshControl={
          <RefreshControl refreshing={isRefreshing} onRefresh={refresh} tintColor={theme.colors.primary} />
        }
        contentContainerStyle={[
          styles.listContent,
          {
            paddingHorizontal: theme.spacing.lg,
            paddingTop: insets.top + theme.spacing.md,
            paddingBottom: insets.bottom + theme.spacing.xxxl,
          },
        ]}
        showsVerticalScrollIndicator={false}
        accessibilityLabel="Group balances and settlements"
      />

      <SettleUpModal
        key={selectedCounterparty ? `${selectedCounterparty.userId}:${selectedCounterparty.netAmountPaise}` : 'closed'}
        visible={selectedCounterparty !== null}
        counterparty={selectedCounterparty}
        currentUserId={user?.id}
        isCurrentUserPayer={selectedCounterparty?.status === 'you_owe'}
        onClose={() => setSelectedCounterparty(null)}
        onSubmit={submitSettlement}
        onSaved={handleSaved}
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
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  centerText: {
    textAlign: 'center',
  },
  fullWidth: {
    width: '100%',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  bordered: {
    borderWidth: 1,
  },
});
