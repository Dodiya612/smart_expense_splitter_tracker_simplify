import React from 'react';
import {
  StyleProp,
  StyleSheet,
  TouchableOpacity,
  View,
  ViewStyle,
} from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';

export interface MaintenanceBannerProps {
  visible?: boolean;
  message?: string;
  subMessage?: string;
  startTime?: string;
  endTime?: string;
  onRefresh?: () => void;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}

/**
 * Maintenance Banner displayed when system maintenance mode is enabled by configuration (US-35 / T-61).
 * Informs users of planned maintenance windows, read-only mode, or temporary service downtime.
 */
export function MaintenanceBanner({
  visible = true,
  message = 'Scheduled maintenance is currently in progress.',
  subMessage = 'Some actions may be temporarily unavailable. Coinscious will resume full operations shortly.',
  startTime,
  endTime,
  onRefresh,
  style,
  testID = 'maintenance-banner',
}: MaintenanceBannerProps) {
  const theme = useTheme();

  if (!visible) return null;

  const timeWindow =
    startTime || endTime
      ? `Window: ${startTime ?? 'Now'} – ${endTime ?? 'TBD'}`
      : null;

  return (
    <View
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
        },
        style,
      ]}
    >
      <View style={[styles.headerRow, { gap: theme.spacing.sm }]}>
        <View
          style={[
            styles.indicatorBadge,
            { backgroundColor: theme.colors.warning.text },
          ]}
        >
          <AppText
            variant="caption"
            style={{ color: '#FFFFFF', fontWeight: '700' }}
          >
            MAINTENANCE
          </AppText>
        </View>
        <AppText
          variant="bodyStrong"
          color="warning"
          style={styles.messageText}
        >
          {message}
        </AppText>
      </View>

      {Boolean(subMessage) && (
        <AppText variant="caption" color="warning">
          {subMessage}
        </AppText>
      )}

      {Boolean(timeWindow) && (
        <AppText
          variant="caption"
          style={[styles.windowText, { color: theme.colors.textSecondary }]}
        >
          {timeWindow}
        </AppText>
      )}

      {Boolean(onRefresh) && (
        <TouchableOpacity
          onPress={onRefresh}
          style={[
            styles.refreshButton,
            {
              backgroundColor: theme.colors.warning.text,
              borderRadius: theme.radii.sm,
              paddingVertical: theme.spacing.xs,
              paddingHorizontal: theme.spacing.sm,
            },
          ]}
          accessibilityRole="button"
          accessibilityLabel="Check again"
        >
          <AppText variant="caption" style={{ color: '#FFFFFF', fontWeight: '600' }}>
            Check Status
          </AppText>
        </TouchableOpacity>
      )}
    </View>
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
  indicatorBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  messageText: {
    flex: 1,
  },
  windowText: {
    fontStyle: 'italic',
  },
  refreshButton: {
    alignSelf: 'flex-start',
    marginTop: 4,
  },
});
