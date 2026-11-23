/**
 * Budgets API Service (T-49 / US-25).
 * Integrates with T-48 backend endpoints:
 * - GET /api/v1/budgets
 * - POST /api/v1/budgets
 * - GET /api/v1/budgets/{id}
 * - PATCH /api/v1/budgets/{id}
 * - DELETE /api/v1/budgets/{id}
 */

import { fastApiClient } from '@/services/api/fastApiClient';
import { ApiError } from '@/services/api/types';
import type {
  Budget,
  BudgetCreatePayload,
  BudgetDataResponse,
  BudgetListResponse,
  BudgetUpdatePayload,
} from '../types';

export type SavingsLevelPercent = 0 | 5 | 10;

export interface BudgetRecommendationRequestPayload {
  categoryId?: string | null;
  savingsLevelPercent?: SavingsLevelPercent;
}

export interface HistoricalMonthSpend {
  month: string;
  spentPaise: number;
  spikePaise: number;
  netPaise: number;
}

export interface RawHistoricalMonthSpend {
  month: string;
  spent_paise?: number;
  spentPaise?: number;
  spike_paise?: number;
  spikePaise?: number;
  net_paise?: number;
  netPaise?: number;
}

export interface RawBudgetRecommendation {
  category_id?: string | null;
  categoryId?: string | null;
  category_name?: string | null;
  categoryName?: string | null;
  savings_level_percent?: number;
  savingsLevelPercent?: number;
  has_sufficient_history?: boolean;
  hasSufficientHistory?: boolean;
  historical_months?: RawHistoricalMonthSpend[];
  historicalMonths?: RawHistoricalMonthSpend[];
  baseline_paise?: number;
  baselinePaise?: number;
  raw_median_paise?: number;
  rawMedianPaise?: number;
  savings_paise?: number;
  savingsPaise?: number;
  recommended_limit_paise?: number;
  recommendedLimitPaise?: number;
  explanation: string;
  source: string;
}

export interface BudgetRecommendation {
  categoryId: string | null;
  categoryName: string | null;
  savingsLevelPercent: SavingsLevelPercent;
  hasSufficientHistory: boolean;
  historicalMonths: HistoricalMonthSpend[];
  baselinePaise: number;
  rawMedianPaise: number;
  savingsPaise: number;
  recommendedLimitPaise: number;
  explanation: string;
  source: 'ai' | 'template_fallback' | string;
}

export interface BudgetRecommendationDataResponse {
  data: RawBudgetRecommendation;
}

export interface RawBudgetProgress {
  period_start?: string;
  periodStart?: string;
  period_end?: string;
  periodEnd?: string;
  spent_paise?: number;
  spentPaise?: number;
  remaining_paise?: number;
  remainingPaise?: number;
  over_by_paise?: number;
  overByPaise?: number;
  percent_used?: number;
  percentUsed?: number;
  status?: 'under' | 'warning' | 'exceeded';
}

export interface RawBudget {
  id: string;
  period: 'weekly' | 'monthly';
  category_id?: string | null;
  categoryId?: string | null;
  limit_paise?: number;
  limitPaise?: number;
  created_at?: string;
  createdAt?: string;
  updated_at?: string;
  updatedAt?: string;
  progress?: RawBudgetProgress;
}

/**
 * Normalizes raw backend budget objects to frontend camelCase Budget.
 */
export function mapBudget(raw: RawBudget): Budget {
  const p = raw.progress || {};
  const limitPaise = raw.limitPaise ?? raw.limit_paise ?? 0;
  const spentPaise = p.spentPaise ?? p.spent_paise ?? 0;
  const remainingPaise = p.remainingPaise ?? p.remaining_paise ?? (limitPaise - spentPaise);
  const overByPaise = p.overByPaise ?? p.over_by_paise ?? Math.max(0, spentPaise - limitPaise);
  const percentUsed =
    p.percentUsed ??
    p.percent_used ??
    (limitPaise > 0 ? Math.floor((spentPaise * 100) / limitPaise) : 0);

  let status: 'under' | 'warning' | 'exceeded' = p.status || 'under';
  if (!p.status) {
    if (percentUsed >= 100) status = 'exceeded';
    else if (percentUsed >= 80) status = 'warning';
    else status = 'under';
  }

  return {
    id: raw.id,
    period: raw.period,
    categoryId: raw.categoryId ?? raw.category_id ?? null,
    limitPaise,
    createdAt: raw.createdAt ?? raw.created_at ?? new Date().toISOString(),
    updatedAt: raw.updatedAt ?? raw.updated_at ?? new Date().toISOString(),
    progress: {
      periodStart: p.periodStart ?? p.period_start ?? '',
      periodEnd: p.periodEnd ?? p.period_end ?? '',
      spentPaise,
      remainingPaise,
      overByPaise,
      percentUsed,
      status,
    },
  };
}

export const budgetsApi = {
  /**
   * List active budgets with current-period progress.
   */
  async listBudgets(limit = 50, offset = 0): Promise<{ budgets: Budget[]; total: number }> {
    try {
      const res = await fastApiClient.get<BudgetListResponse>(
        `/api/v1/budgets?limit=${limit}&offset=${offset}`
      );
      const items = Array.isArray(res?.data) ? res.data : [];
      return {
        budgets: items.map(mapBudget),
        total: res?.meta?.total ?? items.length,
      };
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError('NETWORK_ERROR', err instanceof Error ? err.message : 'Failed to fetch budgets');
    }
  },

  /**
   * Get a single budget by ID.
   */
  async getBudget(budgetId: string): Promise<Budget> {
    try {
      const res = await fastApiClient.get<BudgetDataResponse>(`/api/v1/budgets/${budgetId}`);
      if (!res?.data) {
        throw new ApiError('NOT_FOUND', 'Budget not found');
      }
      return mapBudget(res.data);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError('NETWORK_ERROR', err instanceof Error ? err.message : 'Failed to fetch budget');
    }
  },

  /**
   * Create a new budget.
   */
  async createBudget(payload: BudgetCreatePayload, idempotencyKey?: string): Promise<Budget> {
    try {
      // Backend expects camelCase (to_camel alias configured in Pydantic schema)
      const body: Record<string, unknown> = {
        period: payload.period,
        limitPaise: payload.limitPaise,
      };
      if (payload.categoryId !== undefined) {
        body.categoryId = payload.categoryId;
      }

      const headers: Record<string, string> = {};
      if (idempotencyKey) {
        headers['Idempotency-Key'] = idempotencyKey;
      }

      const res = await fastApiClient.post<BudgetDataResponse>('/api/v1/budgets', body, headers);
      if (!res?.data) {
        throw new ApiError('INVALID_RESPONSE', 'Invalid response from server');
      }
      return mapBudget(res.data);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError('NETWORK_ERROR', err instanceof Error ? err.message : 'Failed to create budget');
    }
  },

  /**
   * Update an existing budget's limit.
   */
  async updateBudget(budgetId: string, payload: BudgetUpdatePayload): Promise<Budget> {
    try {
      const body = {
        limitPaise: payload.limitPaise,
      };
      const res = await fastApiClient.patch<BudgetDataResponse>(`/api/v1/budgets/${budgetId}`, body);
      if (!res?.data) {
        throw new ApiError('INVALID_RESPONSE', 'Invalid response from server');
      }
      return mapBudget(res.data);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError('NETWORK_ERROR', err instanceof Error ? err.message : 'Failed to update budget');
    }
  },

  /**
   * Delete a budget (HTTP 204 No Content).
   */
  async deleteBudget(budgetId: string): Promise<void> {
    try {
      await fastApiClient.delete<void>(`/api/v1/budgets/${budgetId}`);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError('NETWORK_ERROR', err instanceof Error ? err.message : 'Failed to delete budget');
    }
  },

  /**
   * Get an advisory AI budget recommendation (T-55 / US-25).
   * Supports 0%, 5%, and 10% savings levels for overall or category scopes.
   */
  async getBudgetRecommendation(
    payload?: BudgetRecommendationRequestPayload
  ): Promise<BudgetRecommendation> {
    try {
      const body: Record<string, any> = {};
      if (payload?.categoryId !== undefined) {
        body.categoryId = payload.categoryId;
      }
      if (payload?.savingsLevelPercent !== undefined) {
        body.savingsLevelPercent = payload.savingsLevelPercent;
      }

      const res = await fastApiClient.post<BudgetRecommendationDataResponse>(
        '/api/v1/budgets/recommend',
        body
      );
      if (!res?.data) {
        throw new ApiError('INVALID_RESPONSE', 'Invalid response from server');
      }
      return mapBudgetRecommendation(res.data);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(
        'NETWORK_ERROR',
        err instanceof Error ? err.message : 'Failed to fetch budget recommendation'
      );
    }
  },
};

/**
 * Normalizes raw backend budget recommendation objects to frontend BudgetRecommendation.
 */
export function mapBudgetRecommendation(raw: RawBudgetRecommendation): BudgetRecommendation {
  const rawMonths = raw.historicalMonths ?? raw.historical_months ?? [];
  const historicalMonths: HistoricalMonthSpend[] = rawMonths.map((m) => ({
    month: m.month,
    spentPaise: m.spentPaise ?? m.spent_paise ?? 0,
    spikePaise: m.spikePaise ?? m.spike_paise ?? 0,
    netPaise: m.netPaise ?? m.net_paise ?? 0,
  }));

  const savingsLevel = (raw.savingsLevelPercent ?? raw.savings_level_percent ?? 10) as SavingsLevelPercent;

  return {
    categoryId: raw.categoryId ?? raw.category_id ?? null,
    categoryName: raw.categoryName ?? raw.category_name ?? null,
    savingsLevelPercent: ([0, 5, 10].includes(savingsLevel) ? savingsLevel : 10) as SavingsLevelPercent,
    hasSufficientHistory: Boolean(raw.hasSufficientHistory ?? raw.has_sufficient_history ?? false),
    historicalMonths,
    baselinePaise: raw.baselinePaise ?? raw.baseline_paise ?? 0,
    rawMedianPaise: raw.rawMedianPaise ?? raw.raw_median_paise ?? 0,
    savingsPaise: raw.savingsPaise ?? raw.savings_paise ?? 0,
    recommendedLimitPaise: raw.recommendedLimitPaise ?? raw.recommended_limit_paise ?? 0,
    explanation: raw.explanation || '',
    source: raw.source || 'template_fallback',
  };
}
