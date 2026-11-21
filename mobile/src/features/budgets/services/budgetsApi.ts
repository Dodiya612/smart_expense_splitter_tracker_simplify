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
};
