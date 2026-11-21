/**
 * GroupBalancesScreen component (T-33 / US-10).
 *
 * Implements:
 * - Group Balance Screen showing total net position, you are owed, you owe.
 * - Member balance breakdowns separating people who owe current user vs people user owes.
 * - Debt simplification switch matching T-09 wireframe (Screen 6).
 * - Settle up modal integration with full/partial settlement, payment channels, notes, reminder toggle.
 * - Loading, error, pull-to-refresh, and empty balance states.
 */

import React, { useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Switch,
  View,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { WakingUpBanner } from '@/components/ui/WakingUpBanner';
import { useAuth } from '@/features/auth/context/AuthContext';
import { useTheme } from '@/theme';
import { MemberBalanceCard } from '../components/MemberBalanceCard';
import { NetPositionCard } from '../components/NetPositionCard';
import { SettleUpModal } from '../components/SettleUpModal';
import { GroupBalancesSkeleton } from '../components/GroupBalancesSkeleton';
import {
  useGroupBalances,
  type PeerStanding,
} from '../hooks/useGroupBalances';

export interface GroupBalancesScreenProps {
  groupId?: string;
  groupName?: string;
}

export function GroupBalancesScreen({
  groupId: propGroupId,
  groupName: propGroupName,
}: GroupBalancesScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const params = useLocalSearchParams<{ groupId?: string; groupName?: string }>();

  const activeGroupId = propGroupId || params.groupId || 'default-group-id';
  const displayGroupName = propGroupName || params.groupName || 'Group Balances';

  const {
    balances,
    group,
    isLoading,
    isRefreshing,
    error,
    isSimplified,
    setIsSimplified,
    userNetBalancePaise,
    userYouAreOwedPaise,
    userYouOwePaise,
    peopleWhoOweYou,
    peopleYouOwe,
    settledMembers,
    refresh,
    recordSettlement,
    isSettling,
    settleError,
    clearSettleError,
  } = useGroupBalances({ groupId: activeGroupId });

  // Waking up detection (US-32 / T-62)
  const [isWakingUp, setIsWakingUp] = useState<boolean>(false);
  React.useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (isLoading && !balances) {
      timer = setTimeout(() => {
        setIsWakingUp(true);
      }, 3500);
    } else {
      setIsWakingUp(false);
    }
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [isLoading, balances]);

  // Settle modal state
  const [selectedCounterparty, setSelectedCounterparty] = useState<PeerStanding | null>(null);
  const [isSettleModalVisible, setIsSettleModalVisible] = useState<boolean>(false);
  const [successToast, setSuccessToast] = useState<string | null>(null);

  const handleOpenSettle = (standing: PeerStanding) => {
    setSelectedCounterparty(standing);
    clearSettleError();
    setIsSettleModalVisible(true);
  };

  const handleCloseSettle = () => {
    setIsSettleModalVisible(false);
    setSelectedCounterparty(null);
  };

  const handleSubmitSettlement = async (payload: any) => {
    await recordSettlement(payload);
    setSuccessToast(`Settlement of ₹${((payload.amountPaise || 0) / 100).toFixed(2)} recorded.`);
    setTimeout(() => {
      setSuccessToast(null);
    }, 4000);
  };

  const renderHeader = () => {
    return (
      <View style={[styles.headerContainer, { gap: theme.spacing.md, paddingBottom: theme.spacing.sm }]}>
        {/* Title Bar */}
        <View style={styles.titleRow}>
          <View style={{ flex: 1 }}>
            <AppText variant="heading" color="textPrimary">
              {group?.name || displayGroupName}
            </AppText>
            <AppText variant="caption" color="textSecondary">
              Balances & Settle Up (US-10)
            </AppText>
          </View>
        </View>

        {/* Net Position Card */}
        <NetPositionCard
          netBalancePaise={userNetBalancePaise}
          youAreOwedPaise={userYouAreOwedPaise}
          youOwePaise={userYouOwePaise}
        />

        {/* Debt Simplification Card (Screen 6 Wireframe) */}
        <AppCard
          style={[
            styles.simplifyCard,
            {
              backgroundColor: theme.colors.surface,
              borderColor: theme.colors.border,
              padding: theme.spacing.sm,
            },
          ]}
        >
          <View style={styles.simplifyRow}>
            <View style={{ flex: 1, paddingRight: theme.spacing.sm }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Ionicons name="shuffle-outline" size={16} color={theme.colors.primary} />
                <AppText variant="bodyStrong" color="textPrimary">
                  Simplify Group Debts
                </AppText>
              </View>
              <AppText variant="caption" color="textSecondary" style={{ marginTop: 2 }}>
                Minimizes total payments between members using ledger graph reduction.
              </AppText>
            </View>
            <Switch
              value={isSimplified}
              onValueChange={setIsSimplified}
              accessibilityLabel="Toggle debt simplification"
              trackColor={{ false: theme.colors.border, true: theme.colors.primary }}
            />
          </View>
        </AppCard>

        {/* Success toast banner */}
        {successToast ? (
          <View
            style={[
              styles.successBanner,
              {
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
  };

  // Group sections
  const sectionsData = React.useMemo(() => {
    const list: Array<
      | { type: 'header'; title: string; count: number }
      | { type: 'item'; standing: PeerStanding }
      | { type: 'empty'; message: string }
    > = [];

    // 1. People Who Owe You
    list.push({
      type: 'header',
      title: 'People Who Owe You',
      count: peopleWhoOweYou.length,
    });
    if (peopleWhoOweYou.length > 0) {
      for (const standing of peopleWhoOweYou) {
        list.push({ type: 'item', standing });
      }
    } else {
      list.push({ type: 'empty', message: 'No group members owe you money.' });
    }

    // 2. People You Owe
    list.push({
      type: 'header',
      title: 'People You Owe',
      count: peopleYouOwe.length,
    });
    if (peopleYouOwe.length > 0) {
      for (const standing of peopleYouOwe) {
        list.push({ type: 'item', standing });
      }
    } else {
      list.push({ type: 'empty', message: 'You do not owe money to anyone.' });
    }

    // 3. Settled Members
    if (settledMembers.length > 0) {
      list.push({
        type: 'header',
        title: 'Settled Members',
        count: settledMembers.length,
      });
      for (const standing of settledMembers) {
        list.push({ type: 'item', standing });
      }
    }

    return list;
  }, [peopleWhoOweYou, peopleYouOwe, settledMembers]);

  if (isLoading && !balances) {
    return (
      <View
        style={[styles.root, { backgroundColor: theme.colors.background }]}
        accessibilityRole="alert"
        accessibilityLabel="Loading group balances"
      >
        {isWakingUp && (
          <View style={{ paddingHorizontal: theme.spacing.lg, paddingTop: insets.top + theme.spacing.md }}>
            <WakingUpBanner visible={isWakingUp} />
          </View>
        )}
        <GroupBalancesSkeleton />
      </View>
    );
  }

  if (error && !balances) {
    return (
      <View
        style={[styles.centerContainer, { backgroundColor: theme.colors.background, padding: theme.spacing.xl }]}
        accessibilityRole="alert"
      >
        <Ionicons name="alert-circle-outline" size={48} color={theme.colors.negative.text} />
        <AppText variant="heading" color="textPrimary" style={{ marginTop: theme.spacing.md, textAlign: 'center' }}>
          Could not load balances
        </AppText>
        <AppText variant="body" color="textSecondary" style={{ marginTop: theme.spacing.xs, textAlign: 'center' }}>
          {error.message || 'Unable to connect to balances service.'}
        </AppText>
        <View style={{ marginTop: theme.spacing.lg, width: '100%' }}>
          <Button label="Try Again" variant="primary" fullWidth onPress={() => refresh()} />
        </View>
      </View>
    );
  }

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <FlatList
        data={sectionsData}
        keyExtractor={(item, index) =>
          item.type === 'item' ? item.standing.userId : `${item.type}-${index}`
        }
        ListHeaderComponent={renderHeader}
        renderItem={({ item }) => {
          if (item.type === 'header') {
            return (
              <View style={[styles.sectionHeader, { marginTop: theme.spacing.md, marginBottom: theme.spacing.xs }]}>
                <AppText variant="bodyStrong" color="textPrimary">
                  {item.title} ({item.count})
                </AppText>
              </View>
            );
          }
          if (item.type === 'empty') {
            return (
              <View
                style={[
                  styles.emptySectionBox,
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
          return (
            <View style={{ marginBottom: theme.spacing.xs }}>
              <MemberBalanceCard
                standing={item.standing}
                onSettlePress={handleOpenSettle}
                canSettle={item.standing.status !== 'settled'}
              />
            </View>
          );
        }}
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
          },
        ]}
        showsVerticalScrollIndicator={false}
        accessibilityRole="list"
        accessibilityLabel="Group balances and settlement list"
      />

      {/* Settle Up Modal */}
      <SettleUpModal
        visible={isSettleModalVisible}
        counterparty={selectedCounterparty}
        currentUserId={user?.id}
        isCurrentUserPayer={selectedCounterparty?.status === 'you_owe'}
        onClose={handleCloseSettle}
        onSubmit={handleSubmitSettlement}
        isSubmitting={isSettling}
        error={settleError}
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
  centerContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerContainer: {
    width: '100%',
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  simplifyCard: {
    borderWidth: 1,
  },
  simplifyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sectionHeader: {
    paddingHorizontal: 2,
  },
  emptySectionBox: {
    borderWidth: 1,
  },
  successBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderWidth: 1,
  },
});
