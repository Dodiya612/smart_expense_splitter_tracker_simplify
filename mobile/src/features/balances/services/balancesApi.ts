/**
 * Group Balances & Settlement API Service (T-33 / US-10).
 *
 * Integrates with T-32 backend endpoints:
 * - GET  /api/v1/groups/:groupId/balances
 * - GET  /api/v1/groups/:groupId/balances/simplified
 * - POST /api/v1/groups/:groupId/settlements
 * - GET  /api/v1/groups/:groupId/settlements
 * - GET  /api/v1/groups/:groupId
 */

import { fastApiClient } from '@/services/api/fastApiClient';
import { ApiError } from '@/services/api/types';
import type {
  GroupBalances,
  GroupDetail,
  MemberBalance,
  SettlementCreatePayload,
  SettlementRecord,
  SimplifiedRepayments,
  SuggestedTransfer,
} from '../types';

interface RawTransfer {
  from_user?: string;
  fromUser?: string;
  to_user?: string;
  toUser?: string;
  amount_paise?: number;
  amountPaise?: number;
}

interface RawMemberBalance {
  user_id?: string;
  userId?: string;
  net_balance_paise?: number;
  netBalancePaise?: number;
  owes_paise?: number;
  owesPaise?: number;
  receives_paise?: number;
  receivesPaise?: number;
  status?: string;
}

interface RawGroupBalancesResponse {
  group_id?: string;
  groupId?: string;
  net_positions?: Record<string, number>;
  netPositions?: Record<string, number>;
  suggested_transfers?: RawTransfer[];
  suggestedTransfers?: RawTransfer[];
  members?: RawMemberBalance[];
  total_debt_paise?: number;
  totalDebtPaise?: number;
  currency?: string;
}

interface RawSimplifiedResponse {
  group_id?: string;
  groupId?: string;
  suggested_transfers?: RawTransfer[];
  suggestedTransfers?: RawTransfer[];
  total_transfers?: number;
  totalTransfers?: number;
  total_amount_paise?: number;
  totalAmountPaise?: number;
}

interface RawSettlementResponse {
  id: string;
  group_id?: string;
  groupId?: string;
  payer_id?: string;
  payerId?: string;
  payee_id?: string;
  payeeId?: string;
  amount_paise?: number;
  amountPaise?: number;
  status: string;
  payment_method?: string;
  paymentMethod?: string;
  notes?: string;
  settlement_date?: string;
  settlementDate?: string;
  is_partial?: boolean;
  isPartial?: boolean;
  remaining_debt_paise?: number;
  remainingDebtPaise?: number;
  created_at: string;
  updated_at: string;
}

function mapTransfer(raw: RawTransfer): SuggestedTransfer {
  return {
    fromUser: raw.from_user ?? raw.fromUser ?? '',
    toUser: raw.to_user ?? raw.toUser ?? '',
    amountPaise: raw.amount_paise ?? raw.amountPaise ?? 0,
  };
}

function mapMemberBalance(raw: RawMemberBalance): MemberBalance {
  const net = raw.net_balance_paise ?? raw.netBalancePaise ?? 0;
  const status = raw.status ?? (net > 0 ? 'creditor' : net < 0 ? 'debtor' : 'settled');
  return {
    userId: raw.user_id ?? raw.userId ?? '',
    netBalancePaise: net,
    owesPaise: raw.owes_paise ?? raw.owesPaise ?? (net < 0 ? Math.abs(net) : 0),
    receivesPaise: raw.receives_paise ?? raw.receivesPaise ?? (net > 0 ? net : 0),
    status: status as MemberBalance['status'],
  };
}

export function mapGroupBalances(
  raw: RawGroupBalancesResponse,
  groupId: string
): GroupBalances {
  const netPositions = raw.net_positions ?? raw.netPositions ?? {};
  const rawTransfers = raw.suggested_transfers ?? raw.suggestedTransfers ?? [];
  const rawMembers = raw.members ?? [];

  const members: MemberBalance[] = rawMembers.length > 0
    ? rawMembers.map(mapMemberBalance)
    : Object.entries(netPositions).map(([uid, net]) => ({
        userId: uid,
        netBalancePaise: net,
        owesPaise: net < 0 ? Math.abs(net) : 0,
        receivesPaise: net > 0 ? net : 0,
        status: net > 0 ? 'creditor' : net < 0 ? 'debtor' : 'settled',
      }));

  const totalDebt = raw.total_debt_paise ?? raw.totalDebtPaise ?? (
    members.filter(m => m.netBalancePaise < 0).reduce((acc, m) => acc + Math.abs(m.netBalancePaise), 0)
  );

  return {
    groupId: raw.group_id ?? raw.groupId ?? groupId,
    netPositions,
    suggestedTransfers: rawTransfers.map(mapTransfer),
    members,
    totalDebtPaise: totalDebt,
    currency: raw.currency ?? 'INR',
  };
}

export async function fetchGroupBalances(groupId: string): Promise<GroupBalances> {
  const raw = await fastApiClient.get<RawGroupBalancesResponse>(
    `/api/v1/groups/${groupId}/balances`
  );
  return mapGroupBalances(raw, groupId);
}

export async function fetchSimplifiedRepayments(groupId: string): Promise<SimplifiedRepayments> {
  const raw = await fastApiClient.get<RawSimplifiedResponse>(
    `/api/v1/groups/${groupId}/balances/simplified`
  );
  const rawTransfers = raw.suggested_transfers ?? raw.suggestedTransfers ?? [];
  return {
    groupId: raw.group_id ?? raw.groupId ?? groupId,
    suggestedTransfers: rawTransfers.map(mapTransfer),
    totalTransfers: raw.total_transfers ?? raw.totalTransfers ?? rawTransfers.length,
    totalAmountPaise: raw.total_amount_paise ?? raw.totalAmountPaise ?? 0,
  };
}

export async function recordSettlement(
  groupId: string,
  payload: SettlementCreatePayload
): Promise<SettlementRecord> {
  const body: Record<string, any> = {
    payer_id: payload.payerId,
    payee_id: payload.payeeId,
    is_full_settlement: payload.isFullSettlement ?? false,
    payment_method: payload.paymentMethod || 'upi',
    notes: payload.notes,
    settlement_date: payload.settlementDate,
  };

  if (payload.amountPaise !== undefined && payload.amountPaise > 0) {
    body.amount_paise = payload.amountPaise;
  }

  const raw = await fastApiClient.post<RawSettlementResponse>(
    `/api/v1/groups/${groupId}/settlements`,
    body
  );

  return {
    id: raw.id,
    groupId: raw.group_id ?? raw.groupId ?? groupId,
    payerId: raw.payer_id ?? raw.payerId ?? payload.payerId,
    payeeId: raw.payee_id ?? raw.payeeId ?? payload.payeeId,
    amountPaise: raw.amount_paise ?? raw.amountPaise ?? payload.amountPaise ?? 0,
    status: raw.status,
    paymentMethod: raw.payment_method ?? raw.paymentMethod,
    notes: raw.notes,
    settlementDate: raw.settlement_date ?? raw.settlementDate ?? new Date().toISOString().slice(0, 10),
    isPartial: raw.is_partial ?? raw.isPartial ?? false,
    remainingDebtPaise: raw.remaining_debt_paise ?? raw.remainingDebtPaise,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

export async function fetchSettlementHistory(groupId: string): Promise<SettlementRecord[]> {
  const rawList = await fastApiClient.get<RawSettlementResponse[]>(
    `/api/v1/groups/${groupId}/settlements`
  );

  return (rawList || []).map((raw) => ({
    id: raw.id,
    groupId: raw.group_id ?? raw.groupId ?? groupId,
    payerId: raw.payer_id ?? raw.payerId ?? '',
    payeeId: raw.payee_id ?? raw.payeeId ?? '',
    amountPaise: raw.amount_paise ?? raw.amountPaise ?? 0,
    status: raw.status,
    paymentMethod: raw.payment_method ?? raw.paymentMethod,
    notes: raw.notes,
    settlementDate: raw.settlement_date ?? raw.settlementDate ?? '',
    isPartial: raw.is_partial ?? raw.isPartial ?? false,
    remainingDebtPaise: raw.remaining_debt_paise ?? raw.remainingDebtPaise,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  }));
}

export async function fetchGroupDetail(groupId: string): Promise<GroupDetail> {
  const raw = await fastApiClient.get<any>(`/api/v1/groups/${groupId}`);
  return {
    id: raw.id,
    name: raw.name,
    description: raw.description,
    type: raw.type,
    createdBy: raw.created_by,
    members: (raw.members || []).map((m: any) => ({
      userId: m.user_id,
      name: m.name,
      email: m.email,
      role: m.role,
      status: m.status,
    })),
  };
}

export async function fetchUserGroups(): Promise<{ id: string; name: string }[]> {
  const list = await fastApiClient.get<any[]>('/api/v1/groups');
  return (list || []).map((g) => ({
    id: g.id,
    name: g.name,
  }));
}

export { ApiError };
