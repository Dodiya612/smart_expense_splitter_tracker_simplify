/**
 * Date range helpers in Asia/Kolkata timezone (T-43 / US-12).
 */

import type { DateRangePreset } from '../types';

export const DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;

export function formatDateKolkata(date: Date): string {
  // Use Intl to format YYYY-MM-DD in Asia/Kolkata
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
  return formatter.format(date);
}

export function isValidDateFormat(dateStr: string): boolean {
  if (!DATE_REGEX.test(dateStr)) return false;
  const [y, m, d] = dateStr.split('-').map(Number);
  const parsed = new Date(Date.UTC(y, m - 1, d));
  return (
    parsed.getUTCFullYear() === y &&
    parsed.getUTCMonth() === m - 1 &&
    parsed.getUTCDate() === d
  );
}

export interface RangeValidationResult {
  isValid: boolean;
  error?: string;
}

export function validateDateRange(fromStr: string, toStr: string): RangeValidationResult {
  if (!fromStr || !isValidDateFormat(fromStr)) {
    return { isValid: false, error: 'Start date must be in YYYY-MM-DD format.' };
  }
  if (!toStr || !isValidDateFormat(toStr)) {
    return { isValid: false, error: 'End date must be in YYYY-MM-DD format.' };
  }
  if (fromStr > toStr) {
    return { isValid: false, error: 'Start date cannot be after end date.' };
  }
  // Max range 731 days (T-42 backend limit)
  const [fy, fm, fd] = fromStr.split('-').map(Number);
  const [ty, tm, td] = toStr.split('-').map(Number);
  const fromDate = new Date(Date.UTC(fy, fm - 1, fd));
  const toDate = new Date(Date.UTC(ty, tm - 1, td));
  const diffDays = Math.round((toDate.getTime() - fromDate.getTime()) / (1000 * 60 * 60 * 24)) + 1;
  if (diffDays > 731) {
    return { isValid: false, error: 'Date range cannot exceed 2 years (731 days).' };
  }
  return { isValid: true };
}

export function computePresetRange(preset: DateRangePreset, now: Date = new Date()): { from: string; to: string } {
  const todayStr = formatDateKolkata(now);
  const [year, month] = todayStr.split('-').map(Number);

  let fromDate: Date;

  switch (preset) {
    case '1M':
      // 1st of current month
      fromDate = new Date(Date.UTC(year, month - 1, 1));
      break;
    case '3M': {
      // 3 calendar months back from start of month
      const targetMonth = month - 3;
      const targetYear = targetMonth < 0 ? year - 1 : year;
      const normalizedMonth = (targetMonth + 12) % 12;
      fromDate = new Date(Date.UTC(targetYear, normalizedMonth, 1));
      break;
    }
    case '6M': {
      const targetMonth = month - 6;
      const targetYear = targetMonth < 0 ? year - 1 : year;
      const normalizedMonth = (targetMonth + 12) % 12;
      fromDate = new Date(Date.UTC(targetYear, normalizedMonth, 1));
      break;
    }
    case '1Y': {
      fromDate = new Date(Date.UTC(year - 1, month - 1, 1));
      break;
    }
    case 'custom':
    default:
      fromDate = new Date(Date.UTC(year, month - 1, 1));
      break;
  }

  return {
    from: formatDateKolkata(fromDate),
    to: todayStr,
  };
}
