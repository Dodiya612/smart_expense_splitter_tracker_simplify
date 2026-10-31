/**
 * UndoToast – 10-second dismissible toast with an animated countdown bar.
 *
 * Used by T-20 (Delete with confirm and undo, US-08).
 *
 * Props:
 *   visible       – mount/unmount the toast
 *   message       – primary line, e.g. "Expense deleted"
 *   durationMs    – how long the toast lives (default 10 000 ms)
 *   onUndo        – called when the user taps "Undo"
 *   onDismissed   – called when the timer expires OR user explicitly dismisses;
 *                   the caller should treat this as "deletion confirmed"
 *
 * Design:
 *   • Sits at the bottom of the screen above the safe-area inset.
 *   • Dark surface (primary colour) with white text so it stands out.
 *   • A thin accent bar shrinks from full-width to zero over `durationMs`.
 *   • Meets WCAG contrast, minimum touch targets, and live-region rules.
 */

import React, { useCallback, useEffect, useRef } from 'react';
import {
  Animated,
  Pressable,
  StyleSheet,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AppText } from './AppText';
import { useTheme } from '@/theme';

export interface UndoToastProps {
  visible: boolean;
  message: string;
  durationMs?: number;
  onUndo: () => void;
  onDismissed: () => void;
}

export function UndoToast({
  visible,
  message,
  durationMs = 10_000,
  onUndo,
  onDismissed,
}: UndoToastProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  // Animated value for the countdown progress bar (1 → 0)
  const progressAnim = useRef(new Animated.Value(1)).current;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const animRef = useRef<Animated.CompositeAnimation | null>(null);

  const startTimer = useCallback(() => {
    // Reset and run progress bar animation
    progressAnim.setValue(1);
    animRef.current?.stop();
    animRef.current = Animated.timing(progressAnim, {
      toValue: 0,
      duration: durationMs,
      useNativeDriver: false, // width % needs JS driver
    });
    animRef.current.start();

    // Auto-dismiss after durationMs
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      onDismissed();
    }, durationMs);
  }, [durationMs, onDismissed, progressAnim]);

  const cleanup = useCallback(() => {
    animRef.current?.stop();
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  useEffect(() => {
    if (visible) {
      startTimer();
    } else {
      cleanup();
    }
    return cleanup;
  }, [visible, startTimer, cleanup]);

  const handleUndo = useCallback(() => {
    cleanup();
    onUndo();
  }, [cleanup, onUndo]);

  if (!visible) return null;

  return (
    <View
      accessibilityRole="alert"
      accessibilityLiveRegion="assertive"
      accessibilityLabel={`${message}. Tap Undo to restore.`}
      style={[
        styles.container,
        {
          bottom: insets.bottom + theme.spacing.lg,
          marginHorizontal: theme.spacing.lg,
          backgroundColor: theme.colors.primary,
          borderRadius: theme.radii.md,
          ...theme.shadows.floating,
        },
      ]}
    >
      {/* ── Content row ──────────────────────────────────────────── */}
      <View style={styles.row}>
        <AppText
          variant="small"
          color="textOnPrimary"
          style={styles.messageText}
          numberOfLines={1}
        >
          {message}
        </AppText>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Undo deletion"
          onPress={handleUndo}
          style={({ pressed }) => [
            styles.undoBtn,
            {
              minHeight: theme.minTouchTarget,
              minWidth: theme.minTouchTarget,
              paddingHorizontal: theme.spacing.md,
            },
            pressed && styles.pressed,
          ]}
        >
          <AppText variant="bodyStrong" color="textOnPrimary">
            Undo
          </AppText>
        </Pressable>
      </View>

      {/* ── Countdown bar ────────────────────────────────────────── */}
      <View
        style={[
          styles.barTrack,
          { backgroundColor: 'rgba(255,255,255,0.2)', borderRadius: theme.radii.pill }, // design-check-ignore: translucent white track on dark toast
        ]}
      >
        <Animated.View
          style={[
            styles.barFill,
            {
              backgroundColor: 'rgba(255,255,255,0.7)', // design-check-ignore: translucent white progress fill on dark toast
              borderRadius: theme.radii.pill,
              width: progressAnim.interpolate({
                inputRange: [0, 1],
                outputRange: ['0%', '100%'],
              }),
            },
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    left: 0,
    right: 0,
    paddingTop: 12,
    paddingBottom: 10,
    paddingHorizontal: 0,
    overflow: 'hidden',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    gap: 8,
  },
  messageText: {
    flex: 1,
  },
  undoBtn: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  barTrack: {
    height: 3,
    marginTop: 10,
    marginHorizontal: 16,
  },
  barFill: {
    height: '100%',
  },
  pressed: {
    opacity: 0.7,
  },
});
