/**
 * Group Balances & Settlement API Service (T-33 / US-10).
 *
 * T-32 backend endpoints (schemas in backend/openapi.json):
 * - GET  /api/v1/groups/:groupId/balances
 * - GET  /api/v1/groups/:groupId/balances/simplified
 * - POST /api/v1/groups/:groupId/settlements   (optional Idempotency-Key header)
 * - GET  /api/v1/groups/:groupId/settlements
 *
 * Goes through getApiClient(), so EXPO_PUBLIC_USE_MOCK_API=true serves the
 * clearly separate mock in src/services/mock/mockBalances.ts instead.
 * Group names come from the groups feature (GET /api/v1/groups/:groupId).
 */

import { getApiClient } from '@/services/api/client';
import { ApiError } from '@/services/api/types';
import type {
  GroupBalances,
  SettlementCreatePayload,
  SettlementRecord,
  SimplifiedRepayments,
} from '../types';
import {
  mapGroupBalances,
  mapSettlement,
  mapSettlementList,
  mapSimplifiedRepayments,
} from '../utils/parseBalances';

const path = (groupId: string) => `/api/v1/groups/${encodeURIComponent(groupId)}`;

export async function fetchGroupBalances(groupId: string): Promise<GroupBalances> {
  return mapGroupBalances(await getApiClient().get<unknown>(`${path(groupId)}/balances`));
}

export async function fetchSimplifiedRepayments(groupId: string): Promise<SimplifiedRepayments> {
  return mapSimplifiedRepayments(
    await getApiClient().get<unknown>(`${path(groupId)}/balances/simplified`)
  );
}

/** SettlementCreateRequest body; the server rejects unknown fields. */
export function toSettlementRequestBody(payload: SettlementCreatePayload): Record<string, unknown> {
  const body: Record<string, unknown> = {
    payer_id: payload.payerId,
    payee_id: payload.payeeId,
    is_full_settlement: payload.isFullSettlement,
  };
  if (payload.amountPaise !== undefined) body.amount_paise = payload.amountPaise;
  if (payload.paymentMethod) body.payment_method = payload.paymentMethod;
  if (payload.notes) body.notes = payload.notes;
  if (payload.settlementDate) body.settlement_date = payload.settlementDate;
  return body;
}

export async function recordSettlement(
  groupId: string,
  payload: SettlementCreatePayload,
  idempotencyKey: string
): Promise<SettlementRecord> {
  const raw = await getApiClient().post<unknown>(
    `${path(groupId)}/settlements`,
    toSettlementRequestBody(payload),
    { 'Idempotency-Key': idempotencyKey }
  );
  return mapSettlement(raw);
}

export async function fetchSettlementHistory(groupId: string): Promise<SettlementRecord[]> {
  return mapSettlementList(await getApiClient().get<unknown>(`${path(groupId)}/settlements`));
}

export { ApiError };
