import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { useTheme } from '@/theme';
import { useInviteCode } from '../hooks/useInviteCode';

export interface InviteCodeCardProps {
  groupId: string;
  groupName: string;
}

type PendingAction = 'new' | 'off' | null;

/** Admin-only card: show, share, replace or turn off the group's invite code (T-29). */
export function InviteCodeCard({ groupId, groupName }: InviteCodeCardProps) {
  const theme = useTheme();
  const { joinCode, inviteLink, isWorking, error, createNewCode, turnOffCode, share } =
    useInviteCode(groupId);
  const [pending, setPending] = useState<PendingAction>(null);

  const confirm = async () => {
    const action = pending;
    setPending(null);
    if (action === 'new') await createNewCode();
    if (action === 'off') await turnOffCode();
  };

  return (
    <AppCard>
      <View style={{ gap: theme.spacing.sm }}>
        <AppText variant="bodyStrong">Invite people</AppText>
        {joinCode ? (
          <>
            <AppText variant="caption" color="textSecondary">
              Share this code or link. It works for 7 days.
            </AppText>
            <View
              style={[styles.codeBox, { backgroundColor: theme.colors.surfaceMuted, borderRadius: theme.radii.md, padding: theme.spacing.md }]}
              accessible
              accessibilityLabel={`Invite code ${joinCode.code.split('').join(' ')}`}>
              <AppText variant="title" selectable style={{ letterSpacing: theme.spacing.xs }}>
                {joinCode.code}
              </AppText>
            </View>
            {inviteLink ? (
              <AppText variant="caption" color="textSecondary" selectable numberOfLines={2}>
                {inviteLink}
              </AppText>
            ) : null}
            <Button label="Share invite" fullWidth loading={isWorking} onPress={() => share(groupName)} />
            <View style={[styles.row, { gap: theme.spacing.sm }]}>
              <Button label="New code" variant="outline" style={styles.flex} disabled={isWorking} onPress={() => setPending('new')} />
              <Button label="Turn off code" variant="outline" style={styles.flex} disabled={isWorking} onPress={() => setPending('off')} />
            </View>
          </>
        ) : (
          <>
            <AppText variant="small" color="textSecondary">
              For security, a code is shown only when it is created. Create a new one to invite people; any older code stops working.
            </AppText>
            <Button label="Create invite code" fullWidth loading={isWorking} onPress={createNewCode} />
          </>
        )}
        {error ? (
          <AppText variant="caption" color="negative" accessibilityRole="alert">
            {`[!] ${error}`}
          </AppText>
        ) : null}
      </View>
      <ConfirmDialog
        visible={pending !== null}
        title={pending === 'off' ? 'Turn off invite code?' : 'Create a new code?'}
        message={
          pending === 'off'
            ? 'Nobody will be able to join with the current code or link.'
            : 'The current code and link will stop working.'
        }
        confirmLabel={pending === 'off' ? 'Turn off code' : 'Create new code'}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      />
    </AppCard>
  );
}

const styles = StyleSheet.create({
  codeBox: { alignItems: 'center' },
  row: { flexDirection: 'row' },
  flex: { flex: 1 },
});
