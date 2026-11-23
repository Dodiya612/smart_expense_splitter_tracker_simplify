/**
 * Shared expense create call (T-31 / US-18, US-19).
 * POST /api/v1/groups/:groupId/expenses (T-30). The server recomputes every share
 * with the ledger engine; the returned shares are what was saved.
 */

import { fastApiClient } from '@/services/api/fastApiClient';

export interface SavedGroupExpense {
  id: string;
  amountPaise: number;
  shares: { userId: string; amountPaise: number }[];
}

type Raw = Record<string, unknown>;

export async function createGroupExpense(
  groupId: string,
  body: Record<string, unknown>,
  idempotencyKey: string
): Promise<SavedGroupExpense> {
  const raw = await fastApiClient.post<Raw>(
    `/api/v1/groups/${encodeURIComponent(groupId)}/expenses`,
    body,
    { 'Idempotency-Key': idempotencyKey }
  );
  const shares = Array.isArray(raw.shares) ? (raw.shares as Raw[]) : [];
  return {
    id: String(raw.id ?? ''),
    amountPaise: Number(raw.amountPaise ?? raw.amount_paise ?? 0),
    shares: shares.map((s) => ({
      userId: String(s.userId ?? s.user_id ?? ''),
      amountPaise: Number(s.amountPaise ?? s.amount_paise ?? 0),
    })),
  };
}
