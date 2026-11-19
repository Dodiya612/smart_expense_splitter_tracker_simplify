/**
 * MOCK ONLY – balances and settlements for EXPO_PUBLIC_USE_MOCK_API=true (T-33 / US-10).
 *
 * Returns the exact response shapes of the real T-32 endpoints (backend/openapi.json,
 * snake_case) for the PRODUCT.md demo dataset: Alex pays ₹3,000 for groceries split
 * equally with Blair and Casey. The mock signed-in user (usr_mock_1) is Alex.
 *
 * Nothing here is saved anywhere: it is in-memory, per app session, and resets on
 * reload. The real numbers always come from the backend ledger engine; this only
 * imitates it closely enough to exercise the screens.
 */

import { ApiError } from '@/services/api/types';

export const MOCK_ALEX = 'usr_mock_1';
export const MOCK_BLAIR = 'usr_mock_blair';
export const MOCK_CASEY = 'usr_mock_casey';

interface MockSettlement {
  id: string;
  group_id: string;
  payer_id: string;
  payee_id: string;
  amount_paise: number;
  status: 'completed';
  payment_method: string | null;
  notes: string | null;
  settlement_date: string;
  is_partial: boolean;
  remaining_debt_paise: number | null;
  created_at: string;
  updated_at: string;
}

interface MockGroupState {
  /** Demo expense: Alex paid 300000, each share 100000. */
  expenseNet: Record<string, number>;
  settlements: MockSettlement[];
  keys: Map<string, { body: string; response: MockSettlement }>;
}

const groups = new Map<string, MockGroupState>();

function state(groupId: string): MockGroupState {
  let s = groups.get(groupId);
  if (!s) {
    s = {
      expenseNet: { [MOCK_ALEX]: 200000, [MOCK_BLAIR]: -100000, [MOCK_CASEY]: -100000 },
      settlements: [],
      keys: new Map(),
    };
    groups.set(groupId, s);
  }
  return s;
}

/** Test helper: forget all mock state. */
export function resetMockBalances(): void {
  groups.clear();
}

function netPositions(s: MockGroupState): Record<string, number> {
  const net = { ...s.expenseNet };
  for (const st of s.settlements) {
    net[st.payer_id] = (net[st.payer_id] ?? 0) + st.amount_paise;
    net[st.payee_id] = (net[st.payee_id] ?? 0) - st.amount_paise;
  }
  return net;
}

/** Greedy largest-debtor-to-largest-creditor, ties by user id (as the backend does). */
function simplify(net: Record<string, number>) {
  const pos = Object.fromEntries(Object.entries(net).filter(([, v]) => v !== 0));
  const transfers: { from_user: string; to_user: string; amount_paise: number }[] = [];
  for (;;) {
    const ids = Object.keys(pos).sort();
    const debtors = ids.filter((id) => pos[id] < 0);
    const creditors = ids.filter((id) => pos[id] > 0);
    if (!debtors.length || !creditors.length) break;
    const d = debtors.reduce((a, b) => (pos[b] < pos[a] ? b : a));
    const c = creditors.reduce((a, b) => (pos[b] > pos[a] ? b : a));
    const amount = Math.min(-pos[d], pos[c]);
    transfers.push({ from_user: d, to_user: c, amount_paise: amount });
    pos[d] += amount;
    pos[c] -= amount;
    if (pos[d] === 0) delete pos[d];
    if (pos[c] === 0) delete pos[c];
  }
  return transfers;
}

function balancesResponse(groupId: string) {
  const net = netPositions(state(groupId));
  const members = Object.keys(net)
    .sort()
    .map((user_id) => {
      const v = net[user_id];
      return {
        user_id,
        net_balance_paise: v,
        owes_paise: v < 0 ? -v : 0,
        receives_paise: v > 0 ? v : 0,
        status: v > 0 ? 'creditor' : v < 0 ? 'debtor' : 'settled',
      };
    });
  return {
    group_id: groupId,
    net_positions: net,
    suggested_transfers: simplify(net),
    members,
    total_debt_paise: members.reduce((sum, m) => sum + m.receives_paise, 0),
    currency: 'INR',
  };
}

function simplifiedResponse(groupId: string) {
  const transfers = simplify(netPositions(state(groupId)));
  return {
    group_id: groupId,
    suggested_transfers: transfers,
    total_transfers: transfers.length,
    total_amount_paise: transfers.reduce((sum, t) => sum + t.amount_paise, 0),
  };
}

function badRequest(code: string, message: string): ApiError {
  return new ApiError(code, message, false);
}

function createSettlement(groupId: string, body: Record<string, unknown>, key: string | undefined) {
  const s = state(groupId);
  const bodyText = JSON.stringify(body);
  if (key) {
    const seen = s.keys.get(key);
    if (seen) {
      if (seen.body !== bodyText) {
        throw new ApiError('IDEMPOTENCY_CONFLICT', 'Idempotency key has already been used with a different request payload.', false);
      }
      return seen.response;
    }
  }
  const payer = String(body.payer_id ?? '');
  const payee = String(body.payee_id ?? '');
  if (payer === payee) throw badRequest('SELF_SETTLEMENT_PROHIBITED', 'Payer and payee cannot be the same member.');
  const net = netPositions(s);
  if (!(payer in net)) throw badRequest('PAYER_NOT_IN_GROUP', 'Payer is not an active member of this group.');
  if (!(payee in net)) throw badRequest('PAYEE_NOT_IN_GROUP', 'Payee is not an active member of this group.');
  if (net[payer] >= 0) throw badRequest('PAYER_NOT_DEBTOR', 'Payer does not owe anything in this group.');
  if (net[payee] <= 0) throw badRequest('PAYEE_NOT_CREDITOR', 'Payee is not owed anything in this group.');
  const outstanding = Math.min(-net[payer], net[payee]);
  const asked = typeof body.amount_paise === 'number' ? body.amount_paise : undefined;
  const amount = body.is_full_settlement === true ? outstanding : asked;
  if (body.is_full_settlement === true && asked !== undefined && asked !== outstanding) {
    throw badRequest('AMOUNT_MISMATCH', `Full settlement is ${outstanding} paise, but amount_paise was ${asked}. Refresh balances and try again.`);
  }
  if (amount === undefined) throw badRequest('AMOUNT_REQUIRED', 'amount_paise is required unless is_full_settlement is true.');
  if (amount > outstanding) {
    throw badRequest('AMOUNT_EXCEEDS_OUTSTANDING', `Settlement amount (${amount} paise) exceeds what the payer owes the payee (${outstanding} paise).`);
  }
  const now = new Date().toISOString();
  const record: MockSettlement = {
    id: `mock-stl-${s.settlements.length + 1}`,
    group_id: groupId,
    payer_id: payer,
    payee_id: payee,
    amount_paise: amount,
    status: 'completed',
    payment_method: typeof body.payment_method === 'string' ? body.payment_method : null,
    notes: typeof body.notes === 'string' ? body.notes : null,
    settlement_date: typeof body.settlement_date === 'string' ? body.settlement_date : now.slice(0, 10),
    is_partial: amount < outstanding,
    remaining_debt_paise: outstanding - amount,
    created_at: now,
    updated_at: now,
  };
  s.settlements.unshift(record);
  if (key) s.keys.set(key, { body: bodyText, response: record });
  return record;
}

const BALANCES = /^\/api\/v1\/groups\/([^/]+)\/balances$/;
const SIMPLIFIED = /^\/api\/v1\/groups\/([^/]+)\/balances\/simplified$/;
const SETTLEMENTS = /^\/api\/v1\/groups\/([^/]+)\/settlements$/;

/** Mock GET for the balance endpoints, or undefined if the path is not one of them. */
export function mockBalancesGet(endpoint: string): unknown {
  let m = endpoint.match(SIMPLIFIED);
  if (m) return simplifiedResponse(decodeURIComponent(m[1]));
  m = endpoint.match(BALANCES);
  if (m) return balancesResponse(decodeURIComponent(m[1]));
  m = endpoint.match(SETTLEMENTS);
  if (m) {
    const s = state(decodeURIComponent(m[1]));
    return s.settlements.map((st) => ({ ...st, remaining_debt_paise: null }));
  }
  return undefined;
}

/** Mock POST /settlements, or undefined if the path is not it. */
export function mockBalancesPost(endpoint: string, body: unknown, headers?: Record<string, string>): unknown {
  const m = endpoint.match(SETTLEMENTS);
  if (!m) return undefined;
  const payload = body && typeof body === 'object' ? (body as Record<string, unknown>) : {};
  return createSettlement(decodeURIComponent(m[1]), payload, headers?.['Idempotency-Key']);
}
