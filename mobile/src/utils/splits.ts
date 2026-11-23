/**
 * Split preview maths (T-31 / US-19).
 *
 * The server's ledger engine (backend/app/services/ledger.py, allocate()) is the
 * source of truth and recomputes every share on save. This file mirrors its rules
 * so the editor can show a live preview and block unbalanced splits before saving:
 * - equal: base share, leftover paise go to the first participants in order.
 * - exact: whole paise per person; must add up to the total.
 * - percentage: up to 2 decimals per person; must add up to exactly 100.00.
 * - parts: whole numbers of at least 1.
 * Percentage and parts use the largest remainder method with the participant
 * order as the tie-break (ledger.md section 5). Shares always sum to the total.
 *
 * Integer maths only. Totals are capped at ₹1 crore, so every product stays far
 * below Number.MAX_SAFE_INTEGER.
 */

import { parseRupeesToPaise } from './money';

export type SplitMode = 'equal' | 'exact' | 'percentage' | 'parts';

export const SPLIT_MODES: readonly SplitMode[] = ['equal', 'exact', 'percentage', 'parts'];

/** 100.00% expressed in basis points (hundredths of a percent). */
export const FULL_PERCENT_BP = 10_000;
export const MAX_PARTS = 1000;

/** Splits `total` across participants in proportion to integer weights. */
export function allocateByWeights(
  totalPaise: number,
  participantIds: readonly string[],
  weights: readonly number[]
): Record<string, number> {
  const weightSum = weights.reduce((sum, w) => sum + w, 0);
  if (participantIds.length === 0 || weightSum <= 0) return {};
  const base = weights.map((w) => Math.floor((totalPaise * w) / weightSum));
  // Exact remainders as integers: (T * w) mod W, compared without fractions.
  const remainders = weights.map((w) => (totalPaise * w) % weightSum);
  let leftover = totalPaise - base.reduce((sum, s) => sum + s, 0);
  const ranked = participantIds
    .map((_, index) => index)
    .sort((a, b) => remainders[b] - remainders[a] || a - b);
  for (const index of ranked) {
    if (leftover === 0) break;
    base[index] += 1;
    leftover -= 1;
  }
  const shares: Record<string, number> = {};
  participantIds.forEach((id, index) => {
    shares[id] = base[index];
  });
  return shares;
}

/** Equal split: same as weights of 1 each (leftover paise to the first people). */
export function allocateEqual(totalPaise: number, participantIds: readonly string[]): Record<string, number> {
  return allocateByWeights(totalPaise, participantIds, participantIds.map(() => 1));
}

/** Parses "33.33" or "50" into basis points (3333, 5000). Null if invalid or above 100. */
export function parsePercentToBasisPoints(raw: string): number | null {
  const match = raw.trim().match(/^(\d{1,3})(?:\.(\d{0,2}))?$/);
  if (!match) return null;
  const bp = Number(match[1]) * 100 + Number((match[2] ?? '').padEnd(2, '0'));
  return bp <= FULL_PERCENT_BP ? bp : null;
}

/** Parses a whole number of parts (1 to 1000). */
export function parseParts(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d{1,4}$/.test(trimmed)) return null;
  const parts = Number(trimmed);
  return parts >= 1 && parts <= MAX_PARTS ? parts : null;
}

/** Formats basis points as a percent string the backend accepts, e.g. 3333 -> "33.33". */
export function basisPointsToPercentText(bp: number): string {
  return `${Math.floor(bp / 100)}.${String(bp % 100).padStart(2, '0')}`;
}

export interface SplitPreviewInput {
  mode: SplitMode;
  /** Total in paise, or null while the amount field is empty or invalid. */
  totalPaise: number | null;
  /** Participants in the fixed tie order (the group's member order). */
  participantIds: readonly string[];
  /** Raw text typed per participant (rupees, percent or parts, by mode). */
  values: Readonly<Record<string, string>>;
}

export interface SplitPreview {
  /** Share per participant in paise; null where it can't be worked out yet. */
  shares: Record<string, number | null>;
  /** Per-participant input errors. */
  fieldErrors: Record<string, string>;
  /** Exact mode: paise still to assign (negative = too much). */
  remainingPaise: number | null;
  /** Percentage mode: basis points still to assign (negative = too much). */
  remainingBasisPoints: number | null;
  /** True only when the split can be saved. */
  isBalanced: boolean;
  /** Plain-language reason it can't be saved, or null. */
  problem: string | null;
}

function emptyShares(ids: readonly string[]): Record<string, number | null> {
  const shares: Record<string, number | null> = {};
  for (const id of ids) shares[id] = null;
  return shares;
}

export function buildSplitPreview(input: SplitPreviewInput): SplitPreview {
  const { mode, totalPaise, participantIds, values } = input;
  const result: SplitPreview = {
    shares: emptyShares(participantIds),
    fieldErrors: {},
    remainingPaise: null,
    remainingBasisPoints: null,
    isBalanced: false,
    problem: null,
  };

  if (participantIds.length === 0) {
    result.problem = 'Choose at least one person to split with.';
    return result;
  }
  if (totalPaise === null || totalPaise <= 0) {
    result.problem = 'Enter the total amount first.';
    return result;
  }

  if (mode === 'equal') {
    result.shares = allocateEqual(totalPaise, participantIds);
    result.isBalanced = true;
    return result;
  }

  if (mode === 'exact') {
    let assigned = 0;
    for (const id of participantIds) {
      const paise = parseRupeesToPaise(values[id] ?? '');
      if (paise === null) {
        result.fieldErrors[id] = (values[id] ?? '').trim() ? 'Use a number like 250 or 250.50.' : 'Enter an amount.';
      } else {
        result.shares[id] = paise;
        assigned += paise;
      }
    }
    result.remainingPaise = totalPaise - assigned;
    const hasErrors = Object.keys(result.fieldErrors).length > 0;
    result.isBalanced = !hasErrors && result.remainingPaise === 0;
    if (hasErrors) result.problem = 'Fix the highlighted amounts.';
    else if (result.remainingPaise > 0) result.problem = 'The amounts are less than the total.';
    else if (result.remainingPaise < 0) result.problem = 'The amounts are more than the total.';
    return result;
  }

  if (mode === 'percentage') {
    const bps: number[] = [];
    for (const id of participantIds) {
      const bp = parsePercentToBasisPoints(values[id] ?? '');
      if (bp === null) {
        result.fieldErrors[id] = (values[id] ?? '').trim() ? 'Use 0 to 100, up to 2 decimals.' : 'Enter a percentage.';
      }
      bps.push(bp ?? 0);
    }
    const assignedBp = bps.reduce((sum, bp) => sum + bp, 0);
    result.remainingBasisPoints = FULL_PERCENT_BP - assignedBp;
    const hasErrors = Object.keys(result.fieldErrors).length > 0;
    if (!hasErrors && result.remainingBasisPoints === 0) {
      result.shares = allocateByWeights(totalPaise, participantIds, bps);
      result.isBalanced = true;
    } else {
      // Rough preview while unbalanced: each share rounded down, never saved.
      participantIds.forEach((id, i) => {
        if (!result.fieldErrors[id]) result.shares[id] = Math.floor((totalPaise * bps[i]) / FULL_PERCENT_BP);
      });
      if (hasErrors) result.problem = 'Fix the highlighted percentages.';
      else if (result.remainingBasisPoints > 0) result.problem = 'The percentages add up to less than 100%.';
      else result.problem = 'The percentages add up to more than 100%.';
    }
    return result;
  }

  // parts
  const parts: number[] = [];
  for (const id of participantIds) {
    const p = parseParts(values[id] ?? '');
    if (p === null) result.fieldErrors[id] = `Use a whole number from 1 to ${MAX_PARTS}.`;
    parts.push(p ?? 0);
  }
  if (Object.keys(result.fieldErrors).length > 0) {
    result.problem = 'Fix the highlighted parts.';
    return result;
  }
  result.shares = allocateByWeights(totalPaise, participantIds, parts);
  result.isBalanced = true;
  return result;
}

/**
 * The `split_weights` the backend expects for a balanced split, keyed by user id.
 * exact: paise (int) · percentage: "33.33" strings (parsed with Decimal server-side)
 * · parts: int · equal: undefined.
 */
export function toSplitWeights(
  mode: SplitMode,
  participantIds: readonly string[],
  values: Readonly<Record<string, string>>
): Record<string, number | string> | undefined {
  if (mode === 'equal') return undefined;
  const weights: Record<string, number | string> = {};
  for (const id of participantIds) {
    const raw = values[id] ?? '';
    if (mode === 'exact') weights[id] = parseRupeesToPaise(raw) ?? 0;
    else if (mode === 'percentage') weights[id] = basisPointsToPercentText(parsePercentToBasisPoints(raw) ?? 0);
    else weights[id] = parseParts(raw) ?? 0;
  }
  return weights;
}
