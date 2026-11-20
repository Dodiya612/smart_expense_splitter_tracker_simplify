/**
 * Balance labels and "who owes whom" from the current user's view (T-33 / US-10).
 *
 * Pure functions (no React, no API) so they can be unit tested.
 * - The headline comes from the current user's net position (positive = others
 *   owe you, ledger.md): "You owe ₹X", "You are owed ₹X" or "Settled up".
 * - Per-person rows come from the ledger engine's simplified repayments:
 *   "Y owes you ₹X" / "You owe Y ₹X".
 * - Wording records settlements; it never says the app moved money.
 */

import { formatPaise } from '@/utils/money';
import type { PeerStanding, SettlementRecord, SuggestedTransfer } from '../types';

export interface MemberInfo {
  userId: string;
  name: string;
  email?: string;
}

export const UNKNOWN_MEMBER_NAME = 'Group member';

export function myPositionLabel(netPaise: number): string {
  if (netPaise < 0) return `You owe ${formatPaise(-netPaise)}`;
  if (netPaise > 0) return `You are owed ${formatPaise(netPaise)}`;
  return 'Settled up';
}

export function peerLabel(standing: PeerStanding): string {
  const amount = formatPaise(Math.abs(standing.netAmountPaise));
  if (standing.status === 'owes_you') return `${standing.name} owes you ${amount}`;
  if (standing.status === 'you_owe') return `You owe ${standing.name} ${amount}`;
  return `${standing.name} is settled up`;
}

export interface Standings {
  myNetPaise: number;
  youAreOwedPaise: number;
  youOwePaise: number;
  peopleWhoOweYou: PeerStanding[];
  peopleYouOwe: PeerStanding[];
  settledMembers: PeerStanding[];
}

export interface StandingsInput {
  currentUserId: string | undefined;
  netPositions: Record<string, number>;
  /** Simplified repayments from GET /balances/simplified (or /balances). */
  transfers: SuggestedTransfer[];
  /** Active group members, for names. */
  members: MemberInfo[];
}

export function deriveStandings({ currentUserId, netPositions, transfers, members }: StandingsInput): Standings {
  const byId = new Map(members.map((m) => [m.userId, m]));
  const person = (userId: string) => {
    const info = byId.get(userId);
    return { userId, name: info?.name ?? UNKNOWN_MEMBER_NAME, email: info?.email };
  };

  const result: Standings = {
    myNetPaise: currentUserId ? (netPositions[currentUserId] ?? 0) : 0,
    youAreOwedPaise: 0,
    youOwePaise: 0,
    peopleWhoOweYou: [],
    peopleYouOwe: [],
    settledMembers: [],
  };
  if (!currentUserId) return result;

  for (const t of transfers) {
    if (t.toUser === currentUserId) {
      result.youAreOwedPaise += t.amountPaise;
      result.peopleWhoOweYou.push({ ...person(t.fromUser), netAmountPaise: t.amountPaise, status: 'owes_you' });
    } else if (t.fromUser === currentUserId) {
      result.youOwePaise += t.amountPaise;
      result.peopleYouOwe.push({ ...person(t.toUser), netAmountPaise: -t.amountPaise, status: 'you_owe' });
    }
  }

  // "Settled up" only for members whose own net position is zero. Someone who
  // still owes (or is owed by) another member is not shown as settled.
  for (const m of members) {
    if (m.userId !== currentUserId && (netPositions[m.userId] ?? 0) === 0) {
      result.settledMembers.push({ ...person(m.userId), netAmountPaise: 0, status: 'settled' });
    }
  }
  return result;
}

/** True when the group has no money owed in either direction yet. */
export function hasNoBalances(netPositions: Record<string, number>): boolean {
  return Object.values(netPositions).every((v) => v === 0);
}

/** e.g. "Blair settled ₹1,000.00 with you" (a record, not a payment made in the app). */
export function settlementLabel(
  record: SettlementRecord,
  currentUserId: string | undefined,
  nameOf: (userId: string) => string
): string {
  const payer = record.payerId === currentUserId ? 'You' : nameOf(record.payerId);
  const payee = record.payeeId === currentUserId ? 'you' : nameOf(record.payeeId);
  return `${payer} settled ${formatPaise(record.amountPaise)} with ${payee}`;
}
