/**
 * Budget Types (T-49 / US-25).
 * Matches T-48 backend contract:
 * - backend/app/schemas/budget.py
 * - backend/app/models/budget.py
 */

export type BudgetPeriod = 'weekly' | 'monthly';
export type BudgetStatus = 'under' | 'warning' | 'exceeded';

export interface BudgetProgress {
  periodStart: string; // YYYY-MM-DD
  periodEnd: string;   // YYYY-MM-DD
  spentPaise: number;
  remainingPaise: number; // limit - spent; negative when over limit
  overByPaise: number;    // how far over limit; 0 when not over
  percentUsed: number;    // integer percentage floor(spent * 100 / limit)
  status: BudgetStatus;   // 'under' (<80%), 'warning' (80% to <100%), 'exceeded' (>=100%)
}

export interface Budget {
  id: string; // UUID
  period: BudgetPeriod;
  categoryId: string | null; // null = overall budget
  limitPaise: number;
  createdAt: string;
  updatedAt: string;
  progress: BudgetProgress;
}

export interface BudgetCreatePayload {
  period: BudgetPeriod;
  limitPaise: number;
  categoryId?: string | null;
}

export interface BudgetUpdatePayload {
  limitPaise: number;
}

export interface BudgetListMeta {
  total: number;
  limit: number;
  offset: number;
}

export interface BudgetListResponse {
  data: Budget[];
  meta: BudgetListMeta;
}

export interface BudgetDataResponse {
  data: Budget;
}

/** Standard UI category descriptor */
export interface BudgetCategoryOption {
  id: string | null; // null for overall
  label: string;
  icon?: string;
}
