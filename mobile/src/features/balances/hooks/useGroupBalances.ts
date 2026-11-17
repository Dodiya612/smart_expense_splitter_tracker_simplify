/**
 * useGroupBalances hook (T-33 / US-10).
 *
 * Manages:
 * - Fetching group balances and simplified repayments from real API.
 * - Loading, error, and pull-to-refresh states.
 * - Current user net position derivation (you owe vs you are owed).
 * - Member separation (people who owe current user vs people current user owes).
 * - Settlement execution and dynamic refresh.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@/features/auth/context/AuthContext';
import { ApiError } from '@/services/api/types';
import {
  fetchGroupBalances,
  fetchGroupDetail,
  fetchSimplifiedRepayments,
  recordSettlement as apiRecordSettlement,
} from '../services/balancesApi';
import type {
  GroupBalances,
  GroupDetail,
  MemberBalance,
  SettlementCreatePayload,
  SettlementRecord,
  SuggestedTransfer,
} from '../types';

export interface UseGroupBalancesOptions {
  groupId: string;
}

export interface PeerStanding {
  userId: string;
  name: string;
  email?: string;
  netAmountPaise: number; // positive = owes current user, negative = current user owes them
  status: 'owes_you' | 'you_owe' | 'settled';
}

export interface UseGroupBalancesReturn {
  balances: GroupBalances | null;
  group: GroupDetail | null;
  isLoading: boolean;
  isRefreshing: boolean;
  error: ApiError | null;
  isSimplified: boolean;
  setIsSimplified: (val: boolean) => void;
  simplifiedTransfers: SuggestedTransfer[];
  userNetBalancePaise: number;
  userYouAreOwedPaise: number;
  userYouOwePaise: number;
  peopleWhoOweYou: PeerStanding[];
  peopleYouOwe: PeerStanding[];
  settledMembers: PeerStanding[];
  refresh: () => Promise<void>;
  recordSettlement: (payload: SettlementCreatePayload) => Promise<SettlementRecord>;
  isSettling: boolean;
  settleError: ApiError | null;
  clearSettleError: () => void;
}

export function useGroupBalances({ groupId }: UseGroupBalancesOptions): UseGroupBalancesReturn {
  const { user } = useAuth();
  const currentUserId = user?.id;

  const [balances, setBalances] = useState<GroupBalances | null>(null);
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [simplifiedTransfers, setSimplifiedTransfers] = useState<SuggestedTransfer[]>([]);
  const [isSimplified, setIsSimplified] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<ApiError | null>(null);

  const [isSettling, setIsSettling] = useState<boolean>(false);
  const [settleError, setSettleError] = useState<ApiError | null>(null);

  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadData = useCallback(
    async (refreshing = false) => {
      if (!groupId) return;

      if (refreshing) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }
      setError(null);

      try {
        const [balData, grpData, simpData] = await Promise.all([
          fetchGroupBalances(groupId),
          fetchGroupDetail(groupId).catch(() => null),
          fetchSimplifiedRepayments(groupId).catch(() => null),
        ]);

        if (!isMountedRef.current) return;

        setBalances(balData);
        if (grpData) setGroup(grpData);
        if (simpData) setSimplifiedTransfers(simpData.suggestedTransfers);
      } catch (err) {
        if (!isMountedRef.current) return;
        if (err instanceof ApiError) {
          setError(err);
        } else {
          setError(
            new ApiError('BALANCES_FETCH_FAILED', 'Failed to load group balances.', true)
          );
        }
      } finally {
        if (isMountedRef.current) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    },
    [groupId]
  );

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const refresh = useCallback(async () => {
    await loadData(true);
  }, [loadData]);

  // Member map for fast name lookup
  const memberNameMap = useMemo(() => {
    const map = new Map<string, { name: string; email?: string }>();
    if (group?.members) {
      for (const m of group.members) {
        map.set(m.userId, { name: m.name, email: m.email });
      }
    }
    return map;
  }, [group]);

  // Derivations for current user standing
  const {
    userNetBalancePaise,
    userYouAreOwedPaise,
    userYouOwePaise,
    peopleWhoOweYou,
    peopleYouOwe,
    settledMembers,
  } = useMemo(() => {
    if (!balances) {
      return {
        userNetBalancePaise: 0,
        userYouAreOwedPaise: 0,
        userYouOwePaise: 0,
        peopleWhoOweYou: [],
        peopleYouOwe: [],
        settledMembers: [],
      };
    }

    const netPositions = balances.netPositions;
    const myNet = currentUserId ? (netPositions[currentUserId] ?? 0) : 0;

    // Use suggested transfers if simplified mode is active, or compute bilateral standings
    const oweYouList: PeerStanding[] = [];
    const youOweList: PeerStanding[] = [];
    const settledList: PeerStanding[] = [];

    let totalOwedToMe = 0;
    let totalIOwe = 0;

    if (currentUserId) {
      // Look at transfers where current user is involved
      const transfers = isSimplified ? (simplifiedTransfers.length > 0 ? simplifiedTransfers : balances.suggestedTransfers) : balances.suggestedTransfers;

      for (const t of transfers) {
        if (t.toUser === currentUserId) {
          // fromUser owes currentUserId
          totalOwedToMe += t.amountPaise;
          const info = memberNameMap.get(t.fromUser);
          oweYouList.push({
            userId: t.fromUser,
            name: info?.name || `Member (${t.fromUser.slice(0, 6)})`,
            email: info?.email,
            netAmountPaise: t.amountPaise,
            status: 'owes_you',
          });
        } else if (t.fromUser === currentUserId) {
          // currentUserId owes toUser
          totalIOwe += t.amountPaise;
          const info = memberNameMap.get(t.toUser);
          youOweList.push({
            userId: t.toUser,
            name: info?.name || `Member (${t.toUser.slice(0, 6)})`,
            email: info?.email,
            netAmountPaise: -t.amountPaise,
            status: 'you_owe',
          });
        }
      }

      // Check all active members to find settled ones
      if (group?.members) {
        const involvedUids = new Set([
          ...oweYouList.map((p) => p.userId),
          ...youOweList.map((p) => p.userId),
          currentUserId,
        ]);

        for (const m of group.members) {
          if (!involvedUids.has(m.userId)) {
            settledList.push({
              userId: m.userId,
              name: m.name,
              email: m.email,
              netAmountPaise: 0,
              status: 'settled',
            });
          }
        }
      }
    } else {
      // If current user is not determined yet, classify members from member balances
      for (const m of balances.members) {
        const info = memberNameMap.get(m.userId);
        const standing: PeerStanding = {
          userId: m.userId,
          name: info?.name || `Member (${m.userId.slice(0, 6)})`,
          email: info?.email,
          netAmountPaise: m.netBalancePaise,
          status: m.netBalancePaise > 0 ? 'owes_you' : m.netBalancePaise < 0 ? 'you_owe' : 'settled',
        };
        if (m.netBalancePaise > 0) {
          oweYouList.push(standing);
          totalOwedToMe += m.netBalancePaise;
        } else if (m.netBalancePaise < 0) {
          youOweList.push(standing);
          totalIOwe += Math.abs(m.netBalancePaise);
        } else {
          settledList.push(standing);
        }
      }
    }

    return {
      userNetBalancePaise: myNet,
      userYouAreOwedPaise: totalOwedToMe,
      userYouOwePaise: totalIOwe,
      peopleWhoOweYou: oweYouList,
      peopleYouOwe: youOweList,
      settledMembers: settledList,
    };
  }, [balances, currentUserId, isSimplified, simplifiedTransfers, memberNameMap, group]);

  const recordSettlement = useCallback(
    async (payload: SettlementCreatePayload): Promise<SettlementRecord> => {
      setIsSettling(true);
      setSettleError(null);
      try {
        const result = await apiRecordSettlement(groupId, payload);
        // Refresh balances dynamically after settlement
        await loadData(true);
        return result;
      } catch (err) {
        if (err instanceof ApiError) {
          setSettleError(err);
          throw err;
        }
        const errorObj = new ApiError(
          'SETTLEMENT_FAILED',
          'Could not record settlement. Please check the details and try again.',
          true
        );
        setSettleError(errorObj);
        throw errorObj;
      } finally {
        if (isMountedRef.current) {
          setIsSettling(false);
        }
      }
    },
    [groupId, loadData]
  );

  const clearSettleError = useCallback(() => {
    setSettleError(null);
  }, []);

  return {
    balances,
    group,
    isLoading,
    isRefreshing,
    error,
    isSimplified,
    setIsSimplified,
    simplifiedTransfers,
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
  };
}
