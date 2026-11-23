import React from 'react';
import { View } from 'react-native';
import { Href, router } from 'expo-router';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { useTheme } from '@/theme';
import { useLeaveGroup } from '../hooks/useLeaveGroup';
import type { GroupDetail } from '../types';
import { leaveDialogText } from '../utils/leaveGroup';
import { LeaveGroupWarning } from './LeaveGroupWarning';

export interface LeaveGroupSectionProps {
  group: GroupDetail;
  currentUserId?: string;
}

/** "Leave group" at the bottom of the group screen (T-35 / US-22). */
export function LeaveGroupSection({ group, currentUserId }: LeaveGroupSectionProps) {
  const theme = useTheme();
  const leave = useLeaveGroup(group.id, currentUserId);
  const isOwner = !!currentUserId && group.createdBy === currentUserId;
  const text = leave.check ? leaveDialogText(leave.check, group.name) : null;
  const showing = leave.step === 'confirm' || leave.step === 'leaving';
  const hasBalance = leave.check !== null && leave.check.kind !== 'settled';

  const handleLeave = async () => {
    if (await leave.confirmLeave()) router.replace('/(tabs)/groups' as Href);
  };

  const settleUp = () => {
    leave.cancel();
    router.push({ pathname: '/group-balances', params: { groupId: group.id, groupName: group.name } } as Href);
  };

  if (isOwner) {
    return (
      <AppText variant="caption" color="textSecondary" style={{ marginTop: theme.spacing.xl }}>
        {"You created this group, so you can't leave it."}
      </AppText>
    );
  }

  return (
    <View style={{ gap: theme.spacing.sm, marginTop: theme.spacing.xl }}>
      <Button
        label="Leave group"
        variant="outline"
        fullWidth
        loading={leave.step === 'checking'}
        disabled={!currentUserId}
        accessibilityHint="Checks your balance, then asks you to confirm"
        onPress={leave.start}
      />
      {leave.error ? (
        <AppText variant="small" color="negative" accessibilityRole="alert">
          {`[!] ${leave.error}`}
        </AppText>
      ) : null}
      <ConfirmDialog
        visible={showing && !hasBalance && text !== null}
        title={text?.title ?? ''}
        message={text?.message ?? ''}
        confirmLabel="Leave group"
        onConfirm={handleLeave}
        onCancel={leave.cancel}
        isLoading={leave.step === 'leaving'}
      />
      <LeaveGroupWarning
        visible={showing && hasBalance && text !== null}
        title={text?.title ?? ''}
        message={text?.message ?? ''}
        isLeaving={leave.step === 'leaving'}
        onSettleUp={settleUp}
        onLeaveAnyway={handleLeave}
        onCancel={leave.cancel}
      />
    </View>
  );
}
