/**
 * Analytics Domain Models & Contracts (T-43 / US-12).
 *
 * Aligned with backend T-42 Pydantic schemas (backend/app/schemas/analytics.py):
 * - Monetary figures strictly in integer paise (1 INR = 100 paise).
 * - Dates in Asia/Kolkata calendar format (YYYY-MM-DD).
 * - "Your Share" counts personal expenses + allocated share of group expenses.
 * - "Cash Paid" counts personal expenses + user's physical payments in group expenses.
 */

export type AnalyticsGranularity = 'day' | 'week' | 'month';

export type SpendingViewMode = 'share' | 'cash_paid';

export type DateRangePreset = '1M' | '3M' | '6M' | '1Y' | 'custom';

export interface AnalyticsRangeParams {
  from?: string; // YYYY-MM-DD
  to?: string; // YYYY-MM-DD
  groupId?: string;
  granularity?: AnalyticsGranularity;
}

export interface AnalyticsSummary {
  fromDate: string;
  toDate: string;
  timezone: string;
  groupId: string | null;
  sharePaise: number;
  cashPaidPaise: number;
  expenseCount: number;
  owedToYouPaise: number;
  youOwePaise: number;
}

export interface TrendBucket {
  bucketStart: string; // YYYY-MM-DD
  bucketEnd: string; // YYYY-MM-DD
  sharePaise: number;
  cashPaidPaise: number;
  cumulativeSharePaise: number;
  cumulativeCashPaidPaise: number;
}

export interface AnalyticsTrends {
  fromDate: string;
  toDate: string;
  timezone: string;
  groupId: string | null;
  granularity: AnalyticsGranularity;
  buckets: TrendBucket[];
  totalSharePaise: number;
  totalCashPaidPaise: number;
}

export interface CategoryBreakdownItem {
  categoryId: string;
  categoryName: string;
  sharePaise: number;
  cashPaidPaise: number;
  expenseCount: number;
}

export interface AnalyticsCategories {
  fromDate: string;
  toDate: string;
  timezone: string;
  groupId: string | null;
  categories: CategoryBreakdownItem[];
  totalSharePaise: number;
  totalCashPaidPaise: number;
}
