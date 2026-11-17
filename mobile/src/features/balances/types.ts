/**
 * Domain types for Group Balances and Settle Up (T-33 / US-10).
 *
 * Monetary values are strictly stored as integer paise (1 INR = 100 paise).
 */

export type BalanceStatus = 'creditor' | 'debtor' | 'settled';

export interface MemberBalance {
  userId: string;
  name?: string;
  email?: string;
  netBalancePaise: number;
  owesPaise: number;
  receivesPaise: number;
  status: BalanceStatus;
}

export interface SuggestedTransfer {
  fromUser: string;
  fromUserName?: string;
  toUser: string;
  toUserName?: string;
  amountPaise: number;
}

export interface GroupBalances {
  groupId: string;
  netPositions: Record<string, number>;
  suggestedTransfers: SuggestedTransfer[];
  members: MemberBalance[];
  totalDebtPaise: number;
  currency: string;
}

export interface SimplifiedRepayments {
  groupId: string;
  suggestedTransfers: SuggestedTransfer[];
  totalTransfers: number;
  totalAmountPaise: number;
}

export interface SettlementRecord {
  id: string;
  groupId: string;
  payerId: string;
  payeeId: string;
  amountPaise: number;
  status: string;
  paymentMethod?: string;
  notes?: string;
  settlementDate: string;
  isPartial: boolean;
  remainingDebtPaise?: number;
  createdAt: string;
  updatedAt: string;
}

export interface SettlementCreatePayload {
  payerId: string;
  payeeId: string;
  amountPaise?: number;
  isFullSettlement?: boolean;
  paymentMethod?: 'upi' | 'cash' | 'bank_transfer' | string;
  notes?: string;
  settlementDate?: string;
  sendReminder?: boolean;
}

export interface GroupMemberInfo {
  userId: string;
  name: string;
  email: string;
  role: string;
  status: string;
}

export interface GroupDetail {
  id: string;
  name: string;
  description?: string;
  type: string;
  createdBy: string;
  members: GroupMemberInfo[];
}
