/**
 * Invite link route (T-29 / US-17): /join/<code>.
 * Deep links such as mobile://join/7K3MQ9XA (or exp://<host>/--/join/7K3MQ9XA in
 * Expo Go) open here with the code prefilled.
 */

import React from 'react';
import { useLocalSearchParams } from 'expo-router';
import { JoinGroupScreen } from '@/features/groups/screens/JoinGroupScreen';

export default function JoinWithCodeRoute() {
  const { code } = useLocalSearchParams<{ code?: string }>();
  const initialCode = typeof code === 'string' ? code : undefined;
  // Keyed by code so opening a second invite link resets the form.
  return <JoinGroupScreen key={initialCode} initialCode={initialCode} />;
}
