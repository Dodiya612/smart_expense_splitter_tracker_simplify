/**
 * Parsers for the T-32 balances and settlements API (T-33 / US-10).
 *
 * Field names and types follow backend/openapi.json exactly. These schemas are
 * plain snake_case (not the camelCase BaseSchema), so there are no camelCase
 * fallbacks. Money must be integer paise; anything else is rejected so a wrong
 * figure is never shown.
 */

import { ApiError } from '@/services/api/types';
import type {
  BalanceStatus,
  GroupBalances,
  MemberBalance,
  SettlementRecord,
  SimplifiedRepayments,
  SuggestedTransfer,
} from '../types';

type Raw = Record<string, unknown>;

function invalid(field: string): ApiError {
  return new ApiError(
    'INVALID_RESPONSE',
    `The server sent an unexpected balance response (${field}). Please try again.`,
    true
  );
}

function obj(raw: unknown, field: string): Raw {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw invalid(field);
  return raw as Raw;
}

function list(raw: Raw, key: string): unknown[] {
  const value = raw[key];
  if (!Array.isArray(value)) throw invalid(key);
  return value;
}

function str(raw: Raw, key: string): string {
  const value = raw[key];
  if (typeof value !== 'string') throw invalid(key);
  return value;
}

function optStr(raw: Raw, key: string): string | null {
  const value = raw[key];
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string') throw invalid(key);
  return value;
}

function paise(raw: Raw, key: string): number {
  const value = raw[key];
  if (typeof value !== 'number' || !Number.isInteger(value)) throw invalid(key);
  return value;
}

function count(raw: Raw, key: string): number {
  const value = raw[key];
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw invalid(key);
  return value;
}

const STATUSES: ReadonlySet<string> = new Set<BalanceStatus>(['creditor', 'debtor', 'settled']);

export function parseTransfer(raw: unknown): SuggestedTransfer {
  const r = obj(raw, 'suggested_transfers');
  return {
    fromUser: str(r, 'from_user'),
    toUser: str(r, 'to_user'),
    amountPaise: paise(r, 'amount_paise'),
  };
}

export function parseMemberBalance(raw: unknown): MemberBalance {
  const r = obj(raw, 'members');
  const rawStatus = str(r, 'status');
  if (!STATUSES.has(rawStatus)) throw invalid('status');
  const status = rawStatus as BalanceStatus;
  return {
    userId: str(r, 'user_id'),
    netBalancePaise: paise(r, 'net_balance_paise'),
    owesPaise: paise(r, 'owes_paise'),
    receivesPaise: paise(r, 'receives_paise'),
    status,
  };
}

/** GET /api/v1/groups/{group_id}/balances */
export function mapGroupBalances(raw: unknown): GroupBalances {
  const r = obj(raw, 'balances');
  const positions = obj(r.net_positions, 'net_positions');
  const netPositions: Record<string, number> = {};
  for (const userId of Object.keys(positions)) {
    netPositions[userId] = paise(positions, userId);
  }
  return {
    groupId: str(r, 'group_id'),
    netPositions,
    suggestedTransfers: list(r, 'suggested_transfers').map(parseTransfer),
    members: list(r, 'members').map(parseMemberBalance),
    totalDebtPaise: paise(r, 'total_debt_paise'),
    currency: optStr(r, 'currency') ?? 'INR',
  };
}

/** GET /api/v1/groups/{group_id}/balances/simplified */
export function mapSimplifiedRepayments(raw: unknown): SimplifiedRepayments {
  const r = obj(raw, 'simplified');
  return {
    groupId: str(r, 'group_id'),
    suggestedTransfers: list(r, 'suggested_transfers').map(parseTransfer),
    totalTransfers: count(r, 'total_transfers'),
    totalAmountPaise: paise(r, 'total_amount_paise'),
  };
}

/** SettlementResponse (POST and GET /api/v1/groups/{group_id}/settlements) */
export function mapSettlement(raw: unknown): SettlementRecord {
  const r = obj(raw, 'settlement');
  const remaining = r.remaining_debt_paise;
  return {
    id: str(r, 'id'),
    groupId: str(r, 'group_id'),
    payerId: str(r, 'payer_id'),
    payeeId: str(r, 'payee_id'),
    amountPaise: paise(r, 'amount_paise'),
    status: str(r, 'status'),
    paymentMethod: optStr(r, 'payment_method'),
    notes: optStr(r, 'notes'),
    settlementDate: str(r, 'settlement_date'),
    isPartial: r.is_partial === true,
    remainingDebtPaise: remaining === undefined || remaining === null ? null : paise(r, 'remaining_debt_paise'),
    createdAt: str(r, 'created_at'),
    updatedAt: str(r, 'updated_at'),
  };
}

export function mapSettlementList(raw: unknown): SettlementRecord[] {
  if (!Array.isArray(raw)) throw invalid('settlements');
  return raw.map(mapSettlement);
}
