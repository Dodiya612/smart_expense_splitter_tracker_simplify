/**
 * Leave group flow (T-35 / US-22).
 *
 * 1. "Leave group" checks the user's balance (GET /groups/:id/balances, T-32).
 * 2. A non-zero balance opens a warning with a settle-up shortcut; a zero
 *    balance opens a plain confirmation. Leaving always needs a confirm tap.
 * 3. Confirming calls DELETE /groups/:id/members/:me, which marks the
 *    membership 'left' (history kept).
 * If the balance can't be checked, nothing is left silently: an error with retry shows.
 */

import { useCallback, useState } from 'react';
import { fetchGroupBalances } from '@/features/balances/services/balancesApi';
import { leaveGroup } from '../services/groupsApi';
import { leaveCheckFor, leaveErrorMessage, type LeaveCheck } from '../utils/leaveGroup';
import { toApiError } from './useGroups';

export type LeaveStep = 'idle' | 'checking' | 'confirm' | 'leaving' | 'left';

export function useLeaveGroup(groupId: string, currentUserId: string | undefined) {
  const [step, setStep] = useState<LeaveStep>('idle');
  const [check, setCheck] = useState<LeaveCheck | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async () => {
    if (!currentUserId) return;
    setStep('checking');
    setError(null);
    try {
      const balances = await fetchGroupBalances(groupId);
      setCheck(leaveCheckFor(balances.netPositions[currentUserId] ?? 0));
      setStep('confirm');
    } catch (err) {
      setError(toApiError(err, 'BALANCE_CHECK_FAILED', "Couldn't check your balance.").message +
        ' Try again before leaving.');
      setStep('idle');
    }
  }, [groupId, currentUserId]);

  const cancel = useCallback(() => {
    setStep('idle');
    setCheck(null);
  }, []);

  const confirmLeave = useCallback(async (): Promise<boolean> => {
    if (!currentUserId) return false;
    setStep('leaving');
    setError(null);
    try {
      await leaveGroup(groupId, currentUserId);
      setStep('left');
      return true;
    } catch (err) {
      const apiError = toApiError(err, 'LEAVE_FAILED', 'Could not leave the group. Please try again.');
      setError(leaveErrorMessage(apiError.code, apiError.message));
      setStep('idle');
      setCheck(null);
      return false;
    }
  }, [groupId, currentUserId]);

  return { step, check, error, start, cancel, confirmLeave };
}
