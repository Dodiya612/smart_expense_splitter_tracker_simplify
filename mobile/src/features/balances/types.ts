/**
 * Domain types for Group Balances and Settle Up (T-33 / US-10).
 *
 * These mirror backend/openapi.json (GroupBalancesResponse, MemberBalanceItem,
 * TransferItem, SimplifiedRepaymentsResponse, SettlementResponse,
 * SettlementCreateRequest). Money is always integer paise (1 INR = 100 paise).
 * Sign convention (ledger.md): a positive net position means others owe this member.
 */

export type BalanceStatus = 'creditor' | 'debtor' | 'settled';

/** MemberBalanceItem */
export interface MemberBalance {
  userId: string;
  netBalancePaise: number;
  owesPaise: number;
  receivesPaise: number;
  status: BalanceStatus;
}

/** TransferItem: a repayment suggested by the ledger engine's simplify(). */
export interface SuggestedTransfer {
  fromUser: string;
  toUser: string;
  amountPaise: number;
}

/** GroupBalancesResponse */
export interface GroupBalances {
  groupId: string;
  netPositions: Record<string, number>;
  suggestedTransfers: SuggestedTransfer[];
  members: MemberBalance[];
  totalDebtPaise: number;
  currency: string;
}

/** SimplifiedRepaymentsResponse */
export interface SimplifiedRepayments {
  groupId: string;
  suggestedTransfers: SuggestedTransfer[];
  totalTransfers: number;
  totalAmountPaise: number;
}

/** SettlementResponse */
export interface SettlementRecord {
  id: string;
  groupId: string;
  payerId: string;
  payeeId: string;
  amountPaise: number;
  status: string;
  paymentMethod: string | null;
  notes: string | null;
  settlementDate: string;
  isPartial: boolean;
  remainingDebtPaise: number | null;
  createdAt: string;
  updatedAt: string;
}

/** SettlementCreateRequest (sent as snake_case). */
export interface SettlementCreatePayload {
  payerId: string;
  payeeId: string;
  /** Required unless isFullSettlement is true; must equal the outstanding amount when both are sent. */
  amountPaise?: number;
  isFullSettlement: boolean;
  paymentMethod?: string;
  notes?: string;
  /** Omit to let the server use today's date in Asia/Kolkata. */
  settlementDate?: string;
}

/** One row of "who owes whom" from the current user's point of view. */
export interface PeerStanding {
  userId: string;
  name: string;
  email?: string;
  /** Positive: this person owes the current user. Negative: the current user owes them. */
  netAmountPaise: number;
  status: 'owes_you' | 'you_owe' | 'settled';
}
