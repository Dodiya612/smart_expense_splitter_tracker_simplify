/**
 * Join a group with a code or an invite link (T-29 / US-17).
 *
 * Opened from the Groups tab (empty field) or from a link /join/<code> (prefilled).
 * The user still taps "Join group" (accept) or "Not now" (decline), so opening a
 * link never adds anyone to a group by itself.
 * A logged-out user is sent to login first; the code is remembered and the user
 * returns here afterwards.
 */

import React, { useEffect } from 'react';
import { View } from 'react-native';
import { Href, Redirect, router } from 'expo-router';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { useAuth } from '@/features/auth/context/AuthContext';
import { useTheme } from '@/theme';
import { GroupScreenHeader } from '../components/GroupScreenHeader';
import { GroupStateView } from '../components/GroupStateView';
import { useJoinGroup } from '../hooks/useJoinGroup';
import { extractJoinCode } from '../utils/joinCode';
import { setPendingJoinCode } from '../utils/pendingJoin';

export interface JoinGroupScreenProps {
  initialCode?: string;
}

export function JoinGroupScreen({ initialCode }: JoinGroupScreenProps) {
  const theme = useTheme();
  const { isAuthenticated, isLoading } = useAuth();
  const prefilled = initialCode ? extractJoinCode(initialCode) : '';
  const join = useJoinGroup(prefilled);
  const needsLogin = !isLoading && !isAuthenticated;

  useEffect(() => {
    if (needsLogin && prefilled) setPendingJoinCode(prefilled);
  }, [needsLogin, prefilled]);

  if (isLoading) {
    return <GroupStateView kind="loading" title="Opening invite" />;
  }
  if (needsLogin) {
    return <Redirect href={'/login' as Href} />;
  }

  const handleJoin = async () => {
    const group = await join.submit();
    if (group?.id) {
      router.replace({ pathname: '/groups/[id]', params: { id: group.id } } as Href);
    }
  };

  const leave = () => router.replace('/(tabs)/groups' as Href);

  return (
    <ScreenContainer scrollable>
      <GroupScreenHeader title="Join a group" />
      <View style={{ gap: theme.spacing.lg, marginTop: theme.spacing.sm }}>
        <AppText variant="body" color="textSecondary">
          {prefilled
            ? 'You were invited to a group. Join to see and add shared expenses.'
            : 'Enter the 8-character code or paste the invite link someone sent you.'}
        </AppText>
        <AppInput
          label="Invite code"
          placeholder="e.g. 7K3MQ9XA"
          value={join.input}
          onChangeText={join.setInput}
          error={join.fieldError}
          autoCapitalize="characters"
          autoCorrect={false}
          autoComplete="off"
          returnKeyType="go"
          onSubmitEditing={handleJoin}
        />
        {join.submitError ? (
          <AppText variant="small" color="negative" accessibilityRole="alert">
            {`[!] ${join.submitError}`}
          </AppText>
        ) : null}
        <Button label="Join group" fullWidth loading={join.isSubmitting} onPress={handleJoin} />
        <Button
          label={join.submitErrorCode === 'ALREADY_MEMBER' ? 'Go to my groups' : 'Not now'}
          variant="outline"
          fullWidth
          disabled={join.isSubmitting}
          onPress={leave}
        />
      </View>
    </ScreenContainer>
  );
}
