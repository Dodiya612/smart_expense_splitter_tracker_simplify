import React, { useEffect, useRef } from 'react';
import {
  ActivityIndicator,
  Animated,
  StyleProp,
  StyleSheet,
  View,
  ViewStyle,
} from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';

export interface WakingUpBannerProps {
  visible?: boolean;
  message?: string;
  subMessage?: string;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}

/**
 * "Waking up" indicator displayed when free-tier backend is spinning up from idle sleep.
 * Part of US-32 / T-62 performance and responsiveness requirements.
 */
export function WakingUpBanner({
  visible = true,
  message = 'Our server is waking up. Please wait a moment...',
  subMessage = 'Free hosting sleeps when idle. Initial start may take up to 30–45s. Thank you for your patience!',
  style,
  testID = 'waking-up-banner',
}: WakingUpBannerProps) {
  const theme = useTheme();
  const pulseAnim = useRef(new Animated.Value(0.6)).current;

  useEffect(() => {
    if (!visible) return;
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 1.0,
          duration: 900,
          useNativeDriver: true,
        }),
        Animated.timing(pulseAnim, {
          toValue: 0.6,
          duration: 900,
          useNativeDriver: true,
        }),
      ])
    );
    pulse.start();
    return () => pulse.stop();
  }, [visible, pulseAnim]);

  if (!visible) return null;

  return (
    <Animated.View
      accessibilityRole="alert"
      accessibilityLabel={`${message} ${subMessage ?? ''}`.trim()}
      testID={testID}
      style={[
        styles.container,
        {
          backgroundColor: theme.colors.warning.soft,
          borderColor: theme.colors.warning.text,
          borderRadius: theme.radii.md,
          padding: theme.spacing.md,
          gap: theme.spacing.xs,
          opacity: pulseAnim,
        },
        style,
      ]}
    >
      <View style={[styles.headerRow, { gap: theme.spacing.sm }]}>
        <ActivityIndicator size="small" color={theme.colors.warning.text} />
        <AppText
          variant="bodyStrong"
          color="warning"
          style={styles.messageText}
        >
          {message}
        </AppText>
      </View>
      {Boolean(subMessage) && (
        <AppText
          variant="caption"
          color="warning"
        >
          {subMessage}
        </AppText>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    width: '100%',
    borderWidth: 1,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  messageText: {
    flex: 1,
  },
});
