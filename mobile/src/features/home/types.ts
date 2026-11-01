import type { Expense } from '@/features/expenses/types';

export interface BalanceSummary {
  youAreOwedPaise: number;
  youOwePaise: number;
  netBalancePaise: number;
  isProvisional: boolean;
}

export interface BudgetSummary {
  monthlyLimitPaise: number;
  spentPaise: number;
  remainingPaise: number;
  percentageSpent: number;
}

export interface DashboardSummary {
  monthLabel: string;
  year: number;
  month: number;
  totalSpentPaise: number;
  balances: BalanceSummary;
  budget: BudgetSummary;
  recentExpenses: Expense[];
}
