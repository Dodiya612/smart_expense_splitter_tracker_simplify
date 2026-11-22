/**
 * Invite code actions for group admins (T-29 / US-17): share, new code, turn off.
 * The share link opens /join/<code> in the app (deep link via the app scheme).
 */

import { useCallback, useState } from 'react';
import { Share } from 'react-native';
import * as Linking from 'expo-linking';
import { revokeJoinCode, rotateJoinCode } from '../services/groupsApi';
import type { JoinCode } from '../types';
import { buildInviteMessage, joinPath } from '../utils/joinCode';
import { forgetJoinCode, getRememberedJoinCode, rememberJoinCode } from '../utils/joinCodeCache';
import { toApiError } from './useGroups';

export interface UseInviteCodeReturn {
  joinCode: JoinCode | null;
  inviteLink: string | null;
  isWorking: boolean;
  error: string | null;
  createNewCode: () => Promise<void>;
  turnOffCode: () => Promise<void>;
  share: (groupName: string) => Promise<void>;
}

export function useInviteCode(groupId: string): UseInviteCodeReturn {
  const [joinCode, setJoinCode] = useState<JoinCode | null>(() => getRememberedJoinCode(groupId));
  const [isWorking, setIsWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inviteLink = joinCode ? Linking.createURL(joinPath(joinCode.code)) : null;

  const createNewCode = useCallback(async () => {
    setIsWorking(true);
    setError(null);
    try {
      const next = await rotateJoinCode(groupId);
      rememberJoinCode(next);
      setJoinCode(next);
    } catch (err) {
      setError(toApiError(err, 'JOIN_CODE_FAILED', 'Could not create an invite code.').message);
    } finally {
      setIsWorking(false);
    }
  }, [groupId]);

  const turnOffCode = useCallback(async () => {
    setIsWorking(true);
    setError(null);
    try {
      await revokeJoinCode(groupId);
      forgetJoinCode(groupId);
      setJoinCode(null);
    } catch (err) {
      setError(toApiError(err, 'JOIN_CODE_FAILED', 'Could not turn off the invite code.').message);
    } finally {
      setIsWorking(false);
    }
  }, [groupId]);

  const share = useCallback(
    async (groupName: string) => {
      if (!joinCode || !inviteLink) return;
      setError(null);
      try {
        await Share.share({ message: buildInviteMessage(groupName, joinCode.code, inviteLink) });
      } catch {
        setError('Could not open the share sheet. Read the code out instead.');
      }
    },
    [joinCode, inviteLink]
  );

  return { joinCode, inviteLink, isWorking, error, createNewCode, turnOffCode, share };
}
