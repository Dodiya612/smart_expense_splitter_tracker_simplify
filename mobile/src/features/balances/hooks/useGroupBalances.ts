/**
 * useGroupBalances hook (T-33 / US-10).
 *
 * Loads balances, simplified repayments (ledger simplify()), member names and
 * the settlement history for one group, and derives the current user's view.
 * Fetching never touches state directly; results are applied afterwards, so the
 * initial load in an effect follows the react-hooks rules.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@/features/auth/context/AuthContext';
import { getGroup } from '@/features/groups/services/groupsApi';
import type { GroupDetail } from '@/features/groups/types';
import { ApiError } from '@/services/api/types';
import {
  fetchGroupBalances,
  fetchSettlementHistory,
  fetchSimplifiedRepayments,
  recordSettlement,
} from '../services/balancesApi';
import type {
  GroupBalances,
  PeerStanding,
  SettlementCreatePayload,
  SettlementRecord,
  SuggestedTransfer,
} from '../types';
import { deriveStandings, hasNoBalances, UNKNOWN_MEMBER_NAME } from '../utils/balanceLabels';

export type { PeerStanding } from '../types';

export interface UseGroupBalancesReturn {
  balances: GroupBalances | null;
  group: GroupDetail | null;
  settlements: SettlementRecord[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: ApiError | null;
  isEmpty: boolean;
  userNetBalancePaise: number;
  userYouAreOwedPaise: number;
  userYouOwePaise: number;
  peopleWhoOweYou: PeerStanding[];
  peopleYouOwe: PeerStanding[];
  settledMembers: PeerStanding[];
  nameOf: (userId: string) => string;
  refresh: () => Promise<void>;
  retry: () => Promise<void>;
  /** POST a settlement, then reload balances and the settlement list. Throws on failure. */
  submitSettlement: (payload: SettlementCreatePayload, idempotencyKey: string) => Promise<SettlementRecord>;
}

interface Loaded {
  balances: GroupBalances;
  transfers: SuggestedTransfer[];
  group: GroupDetail | null;
  settlements: SettlementRecord[];
}

type LoadResult = { data: Loaded } | { error: ApiError };

const MISSING_GROUP = new ApiError('NOT_FOUND', 'This group could not be found. Open it from the Groups tab.', false);

async function loadGroup(groupId: string): Promise<LoadResult> {
  try {
    const [balances, simplified, group, settlements] = await Promise.all([
      fetchGroupBalances(groupId),
      fetchSimplifiedRepayments(groupId).catch(() => null),
      getGroup(groupId).catch(() => null),
      fetchSettlementHistory(groupId).catch(() => [] as SettlementRecord[]),
    ]);
    return {
      data: {
        balances,
        // Both come from the ledger engine's simplify(); /balances is the fallback.
        transfers: simplified ? simplified.suggestedTransfers : balances.suggestedTransfers,
        group,
        settlements,
      },
    };
  } catch (err) {
    return {
      error: err instanceof ApiError
        ? err
        : new ApiError('BALANCES_FETCH_FAILED', 'Could not load group balances. Please try again.', true),
    };
  }
}

export function useGroupBalances({ groupId }: { groupId: string | undefined }): UseGroupBalancesReturn {
  const { user } = useAuth();
  const currentUserId = user?.id;

  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(Boolean(groupId));
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<ApiError | null>(groupId ? null : MISSING_GROUP);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const apply = useCallback((result: LoadResult) => {
    if (!mountedRef.current) return;
    if ('data' in result) {
      setLoaded(result.data);
      setError(null);
    } else {
      setError(result.error);
    }
    setIsLoading(false);
    setIsRefreshing(false);
  }, []);

  useEffect(() => {
    if (!groupId) return;
    void loadGroup(groupId).then(apply);
  }, [groupId, apply]);

  const refresh = useCallback(async () => {
    if (!groupId) return;
    setIsRefreshing(true);
    apply(await loadGroup(groupId));
  }, [groupId, apply]);

  const retry = useCallback(async () => {
    if (!groupId) return;
    setIsLoading(true);
    setError(null);
    apply(await loadGroup(groupId));
  }, [groupId, apply]);

  const members = useMemo(
    () => (loaded?.group?.members ?? []).map((m) => ({ userId: m.userId, name: m.name, email: m.email })),
    [loaded]
  );

  const nameOf = useCallback(
    (userId: string) => members.find((m) => m.userId === userId)?.name ?? UNKNOWN_MEMBER_NAME,
    [members]
  );

  const standings = useMemo(
    () =>
      deriveStandings({
        currentUserId,
        netPositions: loaded?.balances.netPositions ?? {},
        transfers: loaded?.transfers ?? [],
        members,
      }),
    [currentUserId, loaded, members]
  );

  const submitSettlement = useCallback(
    async (payload: SettlementCreatePayload, idempotencyKey: string) => {
      if (!groupId) throw MISSING_GROUP;
      const saved = await recordSettlement(groupId, payload, idempotencyKey);
      // Balances and the settlement list both change after a settlement.
      apply(await loadGroup(groupId));
      return saved;
    },
    [groupId, apply]
  );

  return {
    balances: loaded?.balances ?? null,
    group: loaded?.group ?? null,
    settlements: loaded?.settlements ?? [],
    isLoading,
    isRefreshing,
    error,
    isEmpty: loaded ? hasNoBalances(loaded.balances.netPositions) && loaded.settlements.length === 0 : false,
    userNetBalancePaise: standings.myNetPaise,
    userYouAreOwedPaise: standings.youAreOwedPaise,
    userYouOwePaise: standings.youOwePaise,
    peopleWhoOweYou: standings.peopleWhoOweYou,
    peopleYouOwe: standings.peopleYouOwe,
    settledMembers: standings.settledMembers,
    nameOf,
    refresh,
    retry,
    submitSettlement,
  };
}
