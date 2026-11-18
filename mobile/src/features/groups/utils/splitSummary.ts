/**
 * Text for the split editor's summary line (T-31 / US-19). Pure; unit-tested.
 */

import { formatPaise } from '@/utils/money';
import { basisPointsToPercentText, type SplitMode, type SplitPreview } from '@/utils/splits';

/** The "amount left to assign" line. Words, so status never relies on colour. */
export function splitSummaryText(mode: SplitMode, preview: SplitPreview): string {
  if (preview.isBalanced) {
    if (mode === 'exact') return 'Everything is assigned.';
    if (mode === 'percentage') return '100% assigned.';
    return 'Shares add up to the total.';
  }
  if (mode === 'exact' && preview.remainingPaise !== null && Object.keys(preview.fieldErrors).length === 0) {
    return preview.remainingPaise > 0
      ? `${formatPaise(preview.remainingPaise)} left to assign.`
      : `${formatPaise(-preview.remainingPaise)} too much. Lower someone's amount.`;
  }
  if (mode === 'percentage' && preview.remainingBasisPoints !== null && Object.keys(preview.fieldErrors).length === 0) {
    return preview.remainingBasisPoints > 0
      ? `${basisPointsToPercentText(preview.remainingBasisPoints)}% left to assign.`
      : `${basisPointsToPercentText(-preview.remainingBasisPoints)}% too much.`;
  }
  return preview.problem ?? 'The split is not complete yet.';
}
