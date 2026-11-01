import type { Expense } from '@/features/expenses/types';
import type { BudgetSummary, DashboardSummary } from '../types';

/**
 * Formats integer paise into standard Indian Rupee currency format (e.g. ₹1,234.56).
 */
export function formatPaiseToInr(amountPaise: number): string {
  const inrValue = amountPaise / 100;
  return inrValue.toLocaleString('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Returns dynamic month and year string (e.g. "November 2026").
 */
export function getCurrentMonthLabel(date: Date = new Date()): string {
  return date.toLocaleDateString('en-IN', {
    month: 'long',
    year: 'numeric',
  });
}

/**
 * Calculates budget remaining and percentage spent safely.
 * Handles zero and negative limits without NaN or division by zero.
 */
export function calculateBudgetMetrics(
  monthlyLimitPaise: number,
  spentPaise: number
): Pick<BudgetSummary, 'remainingPaise' | 'percentageSpent'> {
  if (monthlyLimitPaise <= 0) {
    return {
      remainingPaise: 0,
      percentageSpent: 0,
    };
  }

  const remainingPaise = monthlyLimitPaise - spentPaise;
  const rawRatio = spentPaise / monthlyLimitPaise;
  const percentageSpent = Math.max(0, Math.min(100, Math.round(rawRatio * 100)));

  return {
    remainingPaise,
    percentageSpent,
  };
}

/**
 * Sums the total expenses in integer paise.
 */
export function calculateTotalSpentPaise(expenses: Expense[]): number {
  return expenses.reduce((sum, item) => sum + item.amountPaise, 0);
}

/**
 * Filters a list of expenses to only those matching the current month and year.
 */
export function filterExpensesForCurrentMonth(
  expenses: Expense[],
  referenceDate: Date = new Date()
): Expense[] {
  const year = referenceDate.getFullYear();
  const month = String(referenceDate.getMonth() + 1).padStart(2, '0');
  const targetPrefix = `${year}-${month}`;

  return expenses.filter((e) => e.date.startsWith(targetPrefix));
}

/**
 * Returns whether the dashboard represents an empty state (no expenses recorded).
 */
export function isDashboardEmpty(dashboard: DashboardSummary): boolean {
  return dashboard.recentExpenses.length === 0 && dashboard.totalSpentPaise === 0;
}
