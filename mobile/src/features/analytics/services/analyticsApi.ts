/**
 * Analytics API Service (T-43 / US-12).
 *
 * Integrates with T-42 backend endpoints:
 * - GET /api/v1/analytics/summary
 * - GET /api/v1/analytics/trends
 * - GET /api/v1/analytics/categories
 *
 * All amounts are integer paise. Zero-filled by the backend.
 */

import { fastApiClient } from '@/services/api/fastApiClient';
import { ApiError } from '@/services/api/types';
import type {
  AnalyticsCategories,
  AnalyticsGranularity,
  AnalyticsRangeParams,
  AnalyticsSummary,
  AnalyticsTrends,
  CategoryBreakdownItem,
  TrendBucket,
} from '../types';

interface RawSummaryResponse {
  from_date: string;
  to_date: string;
  timezone?: string;
  group_id?: string | null;
  share_paise: number;
  cash_paid_paise: number;
  expense_count: number;
  owed_to_you_paise: number;
  you_owe_paise: number;
}

interface RawTrendBucket {
  bucket_start: string;
  bucket_end: string;
  share_paise: number;
  cash_paid_paise: number;
  cumulative_share_paise: number;
  cumulative_cash_paid_paise: number;
}

interface RawTrendsResponse {
  from_date: string;
  to_date: string;
  timezone?: string;
  group_id?: string | null;
  granularity: AnalyticsGranularity;
  buckets: RawTrendBucket[];
  total_share_paise: number;
  total_cash_paid_paise: number;
}

interface RawCategoryItem {
  category_id: string;
  category_name: string;
  share_paise: number;
  cash_paid_paise: number;
  expense_count: number;
}

interface RawCategoriesResponse {
  from_date: string;
  to_date: string;
  timezone?: string;
  group_id?: string | null;
  categories: RawCategoryItem[];
  total_share_paise: number;
  total_cash_paid_paise: number;
}

export function mapSummary(raw: RawSummaryResponse): AnalyticsSummary {
  return {
    fromDate: raw.from_date,
    toDate: raw.to_date,
    timezone: raw.timezone || 'Asia/Kolkata',
    groupId: raw.group_id ?? null,
    sharePaise: raw.share_paise ?? 0,
    cashPaidPaise: raw.cash_paid_paise ?? 0,
    expenseCount: raw.expense_count ?? 0,
    owedToYouPaise: raw.owed_to_you_paise ?? 0,
    youOwePaise: raw.you_owe_paise ?? 0,
  };
}

export function mapTrends(raw: RawTrendsResponse): AnalyticsTrends {
  const buckets: TrendBucket[] = (raw.buckets || []).map((b) => ({
    bucketStart: b.bucket_start,
    bucketEnd: b.bucket_end,
    sharePaise: b.share_paise ?? 0,
    cashPaidPaise: b.cash_paid_paise ?? 0,
    cumulativeSharePaise: b.cumulative_share_paise ?? 0,
    cumulativeCashPaidPaise: b.cumulative_cash_paid_paise ?? 0,
  }));

  return {
    fromDate: raw.from_date,
    toDate: raw.to_date,
    timezone: raw.timezone || 'Asia/Kolkata',
    groupId: raw.group_id ?? null,
    granularity: raw.granularity || 'day',
    buckets,
    totalSharePaise: raw.total_share_paise ?? (buckets.length > 0 ? buckets[buckets.length - 1].cumulativeSharePaise : 0),
    totalCashPaidPaise: raw.total_cash_paid_paise ?? (buckets.length > 0 ? buckets[buckets.length - 1].cumulativeCashPaidPaise : 0),
  };
}

export function mapCategories(raw: RawCategoriesResponse): AnalyticsCategories {
  const categories: CategoryBreakdownItem[] = (raw.categories || []).map((c) => ({
    categoryId: c.category_id,
    categoryName: c.category_name,
    sharePaise: c.share_paise ?? 0,
    cashPaidPaise: c.cash_paid_paise ?? 0,
    expenseCount: c.expense_count ?? 0,
  }));

  return {
    fromDate: raw.from_date,
    toDate: raw.to_date,
    timezone: raw.timezone || 'Asia/Kolkata',
    groupId: raw.group_id ?? null,
    categories,
    totalSharePaise: raw.total_share_paise ?? categories.reduce((sum, c) => sum + c.sharePaise, 0),
    totalCashPaidPaise: raw.total_cash_paid_paise ?? categories.reduce((sum, c) => sum + c.cashPaidPaise, 0),
  };
}

function buildQueryString(params?: AnalyticsRangeParams): string {
  if (!params) return '';
  const searchParams = new URLSearchParams();
  if (params.from) searchParams.append('from', params.from);
  if (params.to) searchParams.append('to', params.to);
  if (params.groupId) searchParams.append('group_id', params.groupId);
  if (params.granularity) searchParams.append('granularity', params.granularity);
  const q = searchParams.toString();
  return q ? `?${q}` : '';
}

export async function fetchAnalyticsSummary(params?: AnalyticsRangeParams): Promise<AnalyticsSummary> {
  const qs = buildQueryString(params);
  const raw = await fastApiClient.get<RawSummaryResponse>(`/api/v1/analytics/summary${qs}`);
  return mapSummary(raw);
}

export async function fetchAnalyticsTrends(params?: AnalyticsRangeParams): Promise<AnalyticsTrends> {
  const qs = buildQueryString(params);
  const raw = await fastApiClient.get<RawTrendsResponse>(`/api/v1/analytics/trends${qs}`);
  return mapTrends(raw);
}

export async function fetchAnalyticsCategories(params?: AnalyticsRangeParams): Promise<AnalyticsCategories> {
  const qs = buildQueryString(params);
  const raw = await fastApiClient.get<RawCategoriesResponse>(`/api/v1/analytics/categories${qs}`);
  return mapCategories(raw);
}

export { ApiError };
