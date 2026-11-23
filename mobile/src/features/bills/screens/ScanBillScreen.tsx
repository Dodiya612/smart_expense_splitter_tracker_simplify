/**
 * Scan a bill (T-54 / US-16): take or choose a photo, wait while it is read,
 * then review the pre-filled expense form. Nothing is saved on this screen.
 *
 * States: choose (idle) · opening the camera/photos · reading the bill · error
 * with "Try again" and "Add it by hand".
 */

import React, { useCallback } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { Image } from 'expo-image';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import { useScanBill } from '../hooks/useScanBill';
import type { BillDraft } from '../types';
import { encodeDraft } from '../utils/billDraft';

export function ScanBillScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  const openReview = useCallback((draft: BillDraft) => {
    router.replace({ pathname: '/add-expense', params: { draft: encodeDraft(draft) } } as Href);
  }, []);
  const { status, error, canRetry, previewUri, takePhoto, choosePhoto, retry } = useScanBill(openReview);

  const busy = status === 'picking' || status === 'scanning';
  const goBack = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)/home' as Href);
  };
  const addByHand = () => router.replace('/add-expense' as Href);

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.background }]}>
      <View
        style={[
          styles.header,
          {
            paddingTop: insets.top + theme.spacing.sm,
            paddingHorizontal: theme.spacing.lg,
            paddingBottom: theme.spacing.md,
            gap: theme.spacing.sm,
            borderBottomColor: theme.colors.border,
            backgroundColor: theme.colors.surface,
          },
        ]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          disabled={status === 'scanning'}
          onPress={goBack}
          style={({ pressed }) => [
            styles.center,
            { minWidth: theme.minTouchTarget, minHeight: theme.minTouchTarget },
            pressed && styles.pressed,
          ]}>
          <Ionicons name="chevron-back" size={24} color={theme.colors.textPrimary} />
        </Pressable>
        <AppText variant="heading" accessibilityRole="header" style={styles.flex}>
          Scan a bill
        </AppText>
      </View>

      <ScrollView
        contentContainerStyle={{
          padding: theme.spacing.lg,
          paddingBottom: insets.bottom + theme.spacing.xxxl,
          gap: theme.spacing.lg,
        }}>
        <AppText variant="body" color="textSecondary">
          Take a clear photo of the whole bill. We read the amount, date, shop and items, and you
          check them before anything is saved.
        </AppText>

        {status === 'scanning' ? (
          <View style={[styles.center, { gap: theme.spacing.md }]} accessibilityLiveRegion="polite">
            {previewUri ? (
              <Image
                source={{ uri: previewUri }}
                style={[styles.preview, { borderRadius: theme.radii.md, borderColor: theme.colors.border }]}
                contentFit="contain"
                accessibilityLabel="The bill photo you picked"
              />
            ) : null}
            <ActivityIndicator size="large" color={theme.colors.primary} />
            <AppText variant="body" color="textSecondary">
              Reading your bill…
            </AppText>
          </View>
        ) : null}

        {status === 'error' && error ? (
          <View
            accessibilityRole="alert"
            accessibilityLiveRegion="assertive"
            style={[
              styles.banner,
              {
                backgroundColor: theme.colors.negative.soft,
                borderColor: theme.colors.negative.text,
                borderRadius: theme.radii.md,
                padding: theme.spacing.md,
                gap: theme.spacing.sm,
              },
            ]}>
            <AppText variant="small" color="negative">
              {`[!] ${error}`}
            </AppText>
            {canRetry ? <Button label="Try again" variant="outline" onPress={retry} /> : null}
          </View>
        ) : null}

        {status !== 'scanning' ? (
          <View style={{ gap: theme.spacing.md }}>
            <Button
              label="Take a photo"
              fullWidth
              loading={status === 'picking'}
              disabled={busy}
              onPress={takePhoto}
              accessibilityHint="Opens the camera to photograph the bill"
            />
            <Button
              label="Choose from photos"
              variant="outline"
              fullWidth
              disabled={busy}
              onPress={choosePhoto}
              accessibilityHint="Pick a JPEG or PNG photo of the bill, up to 5 MB"
            />
            <Button label="Add it by hand instead" variant="secondary" fullWidth disabled={busy} onPress={addByHand} />
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: 1,
  },
  flex: {
    flex: 1,
  },
  center: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  pressed: {
    opacity: 0.6,
  },
  preview: {
    width: '100%',
    height: 240,
    borderWidth: 1,
  },
  banner: {
    width: '100%',
    borderWidth: 1,
  },
});
