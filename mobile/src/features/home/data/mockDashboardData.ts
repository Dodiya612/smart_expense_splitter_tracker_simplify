import type { Expense } from '@/features/expenses/types';
import type { DashboardSummary } from '../types';
import {
  calculateBudgetMetrics,
  calculateTotalSpentPaise,
  getCurrentMonthLabel,
} from '../utils/dashboardSummary';

/**
 * Generates an ISO date string (YYYY-MM-DD) for days relative to the reference date
 * within the current month, preventing stale sample dates.
 */
function createDateInCurrentMonth(daysAgo: number, referenceDate: Date = new Date()): string {
  const d = new Date(referenceDate);
  const currentDay = d.getDate();
  // Ensure the date remains in the same month if possible, or clamps to the 1st
  const targetDay = Math.max(1, currentDay - daysAgo);
  d.setDate(targetDay);
  return d.toISOString().slice(0, 10);
}

/**
 * Creates populated mock/seed data for dashboard demonstration and development.
 * All amounts are stored in integer paise (1 INR = 100 paise).
 */
export function getMockPopulatedDashboardData(referenceDate: Date = new Date()): DashboardSummary {
  const monthLabel = getCurrentMonthLabel(referenceDate);
  const nowIso = referenceDate.toISOString();

  const recentExpenses: Expense[] = [
    {
      id: 'demo-exp-1',
      amountPaise: 45000, // ₹450.00
      categoryId: 'food',
      date: createDateInCurrentMonth(1, referenceDate),
      paymentMode: 'upi',
      notes: 'Team lunch at cafe',
      isRecurring: false,
      version: 1,
      createdAt: nowIso,
      updatedAt: nowIso,
    },
    {
      id: 'demo-exp-2',
      amountPaise: 120000, // ₹1,200.00
      categoryId: 'transport',
      date: createDateInCurrentMonth(3, referenceDate),
      paymentMode: 'card',
      notes: 'Cab to client meeting',
      isRecurring: false,
      version: 1,
      createdAt: nowIso,
      updatedAt: nowIso,
    },
    {
      id: 'demo-exp-3',
      amountPaise: 285000, // ₹2,850.00
      categoryId: 'utilities',
      date: createDateInCurrentMonth(5, referenceDate),
      paymentMode: 'net_banking',
      notes: 'Broadband internet bill',
      isRecurring: true,
      version: 1,
      createdAt: nowIso,
      updatedAt: nowIso,
    },
  ];

  const totalSpentPaise = calculateTotalSpentPaise(recentExpenses);
  const monthlyLimitPaise = 2500000; // ₹25,000.00
  const budgetMetrics = calculateBudgetMetrics(monthlyLimitPaise, totalSpentPaise);

  return {
    monthLabel,
    year: referenceDate.getFullYear(),
    month: referenceDate.getMonth() + 1,
    totalSpentPaise,
    balances: {
      youAreOwedPaise: 340000, // ₹3,400.00
      youOwePaise: 115000, // ₹1,150.00
      netBalancePaise: 225000, // ₹2,250.00
      isProvisional: true, // Clearly marks ledger figures as demo/provisional
    },
    budget: {
      monthlyLimitPaise,
      spentPaise: totalSpentPaise,
      remainingPaise: budgetMetrics.remainingPaise,
      percentageSpent: budgetMetrics.percentageSpent,
    },
    recentExpenses,
  };
}

/**
 * Creates empty mock data representing a brand new account or a month with no expenses.
 */
export function getMockEmptyDashboardData(referenceDate: Date = new Date()): DashboardSummary {
  const monthLabel = getCurrentMonthLabel(referenceDate);

  return {
    monthLabel,
    year: referenceDate.getFullYear(),
    month: referenceDate.getMonth() + 1,
    totalSpentPaise: 0,
    balances: {
      youAreOwedPaise: 0,
      youOwePaise: 0,
      netBalancePaise: 0,
      isProvisional: true,
    },
    budget: {
      monthlyLimitPaise: 0,
      spentPaise: 0,
      remainingPaise: 0,
      percentageSpent: 0,
    },
    recentExpenses: [],
  };
}

export const MOCK_POPULATED_DASHBOARD_DATA = getMockPopulatedDashboardData();
export const MOCK_EMPTY_DASHBOARD_DATA = getMockEmptyDashboardData();
