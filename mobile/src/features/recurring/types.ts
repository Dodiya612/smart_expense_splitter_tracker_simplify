/**
 * Recurring expense types (T-45 / US-14), mirroring RecurringRuleResponse in
 * backend/openapi.json (built by T-44). The server sends camelCase.
 */

import type { RepeatFrequency } from '@/features/expenses/types';

export type { RepeatFrequency };

export type RuleStatus = 'active' | 'paused' | 'cancelled';

export type RuleAction = 'pause' | 'resume' | 'cancel';

export interface RecurringRule {
  id: string;
  groupId: string | null;
  frequency: RepeatFrequency;
  startDate: string;
  endDate: string | null;
  /** Next date an expense will be added; null when none remains (cancelled or ended). */
  nextRunDate: string | null;
  status: RuleStatus;
  amountPaise: number;
  categoryId: string;
  description: string;
  notes: string | null;
  paymentMode: string | null;
}

/** Body for POST /api/v1/recurring (a personal rule). */
export interface CreateRecurringRuleBody {
  frequency: RepeatFrequency;
  startDate: string;
  amountPaise: number;
  categoryId: string;
  description: string;
  notes?: string;
  paymentMode?: string;
}
