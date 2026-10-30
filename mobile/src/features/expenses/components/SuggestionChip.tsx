/**
 * SuggestionChip – T-23b / US-26
 *
 * An inline chip that appears below the Notes field when the AI has a category
 * suggestion.  It:
 *   • Shows the suggested category label and a confidence badge.
 *   • Has an "Accept" button (fills the category field instantly).
 *   • Has a dismiss "×" button to hide without accepting.
 *   • Never blocks saving – if hidden or not shown, the form works normally.
 *   • Announces itself via accessibilityLiveRegion so screen-reader users hear
 *     the suggestion without having to navigate to it.
 *
 * The chip slides in/out with a subtle spring animation.
 */

import React, { useEffect, useRef } from 'react';
import {
  ActivityIndicator,
  Animated,
  Pressable,
  StyleSheet,
  View,
} from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { CATEGORIES } from '../types';

export interface SuggestionChipProps {
  /** Category id suggested by the AI, or null/undefined when no suggestion. */
  suggestedCategoryId: string | null | undefined;
  /** 0–1 confidence from the classifier. */
  confidence?: number;
  /** True while the debounced API call is in flight. */
  isLoading?: boolean;
  /** Called when the user taps "Accept". */
  onAccept: () => void;
  /** Called when the user taps "×" to dismiss. */
  onDismiss: () => void;
  disabled?: boolean;
}

export function SuggestionChip({
  suggestedCategoryId,
  confidence = 0,
  isLoading = false,
  onAccept,
  onDismiss,
  disabled = false,
}: SuggestionChipProps) {
  const theme = useTheme();
  const slideAnim = useRef(new Animated.Value(0)).current;
  const opacityAnim = useRef(new Animated.Value(0)).current;

  const isVisible = isLoading || Boolean(suggestedCategoryId);

  useEffect(() => {
    Animated.parallel([
      Animated.spring(slideAnim, {
        toValue: isVisible ? 1 : 0,
        useNativeDriver: true,
        tension: 60,
        friction: 10,
      }),
      Animated.timing(opacityAnim, {
        toValue: isVisible ? 1 : 0,
        duration: 160,
        useNativeDriver: true,
      }),
    ]).start();
  }, [isVisible, slideAnim, opacityAnim]);

  const category = CATEGORIES.find((c) => c.id === suggestedCategoryId);
  const palette = category ? theme.categoryPalette[category.paletteIndex] : null;

  const confidencePct = Math.round(confidence * 100);

  return (
    <Animated.View
      style={[
        {
          opacity: opacityAnim,
          transform: [
            {
              translateY: slideAnim.interpolate({
                inputRange: [0, 1],
                outputRange: [-8, 0],
              }),
            },
          ],
        },
      ]}
      // Announce when suggestion appears.
      accessibilityLiveRegion="polite"
    >
      {isLoading && !suggestedCategoryId ? (
        <View
          style={[
            styles.chip,
            {
              backgroundColor: theme.colors.surfaceMuted,
              borderColor: theme.colors.border,
              borderRadius: theme.radii.sm,
              paddingVertical: theme.spacing.xs,
              paddingHorizontal: theme.spacing.md,
              minHeight: theme.minTouchTarget,
            },
          ]}
        >
          <ActivityIndicator
            size="small"
            color={theme.colors.textSecondary}
          />
          <AppText variant="caption" color="textSecondary">
            Suggesting…
          </AppText>
        </View>
      ) : category && palette ? (
        <View
          style={[
            styles.chip,
            {
              backgroundColor: palette.soft,
              borderColor: palette.fill,
              borderRadius: theme.radii.sm,
              paddingVertical: theme.spacing.xs,
              paddingHorizontal: theme.spacing.sm,
              minHeight: theme.minTouchTarget,
              gap: theme.spacing.sm,
            },
          ]}
          accessibilityLabel={`AI suggests ${category.label} (${confidencePct}% confidence). Tap Accept or dismiss.`}
        >
          {/* ── Suggestion label ─────────────────────────────── */}
          <View style={styles.labelGroup}>
            <AppText
              variant="caption"
              style={{ color: theme.colors.textSecondary }}
            >
              AI suggests
            </AppText>
            <AppText
              variant="caption"
              style={{
                color: palette.fill,
                fontFamily: theme.fontFamily.semibold,
              }}
            >
              {category.label}
            </AppText>
            {confidencePct > 0 && (
              <View
                style={[
                  styles.confidenceBadge,
                  {
                    backgroundColor: palette.fill + '22',
                    borderRadius: theme.radii.pill,
                    paddingHorizontal: 6,
                    paddingVertical: 1,
                  },
                ]}
              >
                <AppText
                  variant="caption"
                  style={{ color: palette.fill, fontSize: 10 }}
                >
                  {confidencePct}%
                </AppText>
              </View>
            )}
          </View>

          {/* ── Accept button ────────────────────────────────── */}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Accept suggestion: ${category.label}`}
            disabled={disabled}
            onPress={onAccept}
            style={({ pressed }) => [
              styles.actionBtn,
              {
                backgroundColor: palette.fill,
                borderRadius: theme.radii.pill,
                paddingHorizontal: theme.spacing.md,
                minHeight: 28,
              },
              pressed && styles.pressed,
            ]}
          >
            <AppText
              variant="caption"
              style={{
                color: theme.colors.surface,
                fontFamily: theme.fontFamily.semibold,
              }}
            >
              Accept
            </AppText>
          </Pressable>

          {/* ── Dismiss button ───────────────────────────────── */}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Dismiss suggestion"
            disabled={disabled}
            onPress={onDismiss}
            style={({ pressed }) => [
              styles.dismissBtn,
              {
                minHeight: theme.minTouchTarget,
                minWidth: theme.minTouchTarget,
              },
              pressed && styles.pressed,
            ]}
          >
            <AppText
              variant="caption"
              style={{ color: theme.colors.textSecondary }}
            >
              ×
            </AppText>
          </Pressable>
        </View>
      ) : null}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    flexWrap: 'nowrap',
  },
  labelGroup: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexWrap: 'wrap',
  },
  confidenceBadge: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionBtn: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  dismissBtn: {
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  pressed: {
    opacity: 0.65,
  },
});
