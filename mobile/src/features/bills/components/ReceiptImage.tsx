/**
 * The stored bill photo (T-54 / US-16), loaded with the signed-in user's token.
 * Shows loading, error (with Try again) and loaded states.
 */

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { Image } from 'expo-image';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import { receiptImageSource, type ReceiptImageSource } from '../services/billsApi';

export interface ReceiptImageProps {
  receiptId: string;
  /** Height of the frame; the photo is fitted inside it. */
  height?: number;
}

type LoadState = 'loading' | 'loaded' | 'error';

export function ReceiptImage({ receiptId, height = 220 }: ReceiptImageProps) {
  const theme = useTheme();
  const [attempt, setAttempt] = useState(0);
  // Each value is tagged with the load it belongs to, so a new bill or a retry starts as "loading".
  const loadKey = `${receiptId}:${attempt}`;
  const [loaded, setLoaded] = useState<{ key: string; source: ReceiptImageSource } | null>(null);
  const [result, setResult] = useState<{ key: string; state: Exclude<LoadState, 'loading'> } | null>(null);

  useEffect(() => {
    let active = true;
    receiptImageSource(receiptId)
      .then((s) => {
        if (active) setLoaded({ key: loadKey, source: s });
      })
      .catch(() => {
        if (active) setResult({ key: loadKey, state: 'error' });
      });
    return () => {
      active = false;
    };
  }, [receiptId, loadKey]);

  const source = loaded?.key === loadKey ? loaded.source : null;
  const state: LoadState = result?.key === loadKey ? result.state : 'loading';
  const setState = (next: Exclude<LoadState, 'loading'>) => setResult({ key: loadKey, state: next });

  return (
    <View
      style={[
        styles.frame,
        {
          height,
          borderRadius: theme.radii.md,
          borderColor: theme.colors.border,
          backgroundColor: theme.colors.surfaceMuted,
        },
      ]}
      accessible
      accessibilityLabel="Photo of the bill">
      {source && state !== 'error' ? (
        <Image
          key={attempt}
          source={source}
          style={StyleSheet.absoluteFill}
          contentFit="contain"
          cachePolicy="none"
          onLoad={() => setState('loaded')}
          onError={() => setState('error')}
        />
      ) : null}
      {state === 'loading' ? (
        <View style={[styles.center, { gap: theme.spacing.xs }]}>
          <ActivityIndicator color={theme.colors.primary} />
          <AppText variant="caption" color="textSecondary">
            Loading the bill photo
          </AppText>
        </View>
      ) : null}
      {state === 'error' ? (
        <View style={[styles.center, { gap: theme.spacing.sm, padding: theme.spacing.md }]} accessibilityRole="alert">
          <AppText variant="small" color="textSecondary" style={styles.textCenter}>
            {"The bill photo couldn't be loaded."}
          </AppText>
          <Button label="Try again" variant="outline" onPress={() => setAttempt((n) => n + 1)} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    width: '100%',
    borderWidth: 1,
    overflow: 'hidden',
    justifyContent: 'center',
    alignItems: 'center',
  },
  center: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  textCenter: {
    textAlign: 'center',
  },
});
