/**
 * Notification settings (T-36 / US-38): one switch per notification type.
 * Types the server marks as not switchable (security notices) are shown as always on.
 */

import React from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';
import { Href, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AppText } from '@/components/ui/AppText';
import { GroupScreenHeader } from '@/features/groups/components/GroupScreenHeader';
import { useTheme } from '@/theme';
import { NotificationStateView } from '../components/NotificationStateView';
import { useNotificationPreferences } from '../hooks/useNotificationPreferences';
import { preferenceLabel } from '../utils/parseNotifications';

export function NotificationSettingsScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { preferences, isLoading, error, actionError, retry, setEnabled } =
    useNotificationPreferences();

  const frame = {
    flex: 1,
    backgroundColor: theme.colors.background,
    paddingTop: insets.top,
    paddingHorizontal: theme.spacing.lg,
  } as const;

  if (isLoading && !preferences) {
    return (
      <View style={frame}>
        <GroupScreenHeader title="Notification settings" />
        <NotificationStateView kind="loading" title="Loading your settings" />
      </View>
    );
  }

  if (error && !preferences) {
    return (
      <View style={frame}>
        <GroupScreenHeader title="Notification settings" />
        <NotificationStateView
          kind="error"
          title="Could not load settings"
          message={error.message}
          actionLabel="Try again"
          onAction={retry}
        />
      </View>
    );
  }

  return (
    <View style={frame}>
      <GroupScreenHeader title="Notification settings" subtitle="Choose what you hear about" />
      <ScrollView
        contentContainerStyle={{ paddingBottom: Math.max(insets.bottom, theme.spacing.lg) + theme.spacing.lg }}
        showsVerticalScrollIndicator={false}>
        {actionError ? (
          <AppText
            variant="small"
            color="negative"
            accessibilityRole="alert"
            style={{ marginBottom: theme.spacing.sm }}>
            {actionError}
          </AppText>
        ) : null}
        {(preferences ?? []).map((pref) => {
          const { label, hint } = preferenceLabel(pref.kind);
          return (
            <View
              key={pref.kind}
              style={[
                styles.row,
                {
                  minHeight: theme.minTouchTarget,
                  paddingVertical: theme.spacing.md,
                  gap: theme.spacing.md,
                  borderBottomColor: theme.colors.border,
                },
              ]}>
              <View style={styles.text}>
                <AppText variant="bodyStrong">{label}</AppText>
                <AppText variant="small" color="textSecondary">
                  {pref.canDisable ? hint : `${hint}. Always on.`}
                </AppText>
              </View>
              <Switch
                value={pref.enabled}
                disabled={!pref.canDisable}
                onValueChange={(value) => void setEnabled(pref.kind, value)}
                accessibilityLabel={`${label}: ${pref.enabled ? 'on' : 'off'}`}
                trackColor={{ false: theme.colors.borderStrong, true: theme.colors.primary }}
                thumbColor={theme.colors.surface}
              />
            </View>
          );
        })}
        {/* T-50 entry point. Move to the Profile tab once that screen exists. */}
        <AppText variant="small" color="textSecondary" style={{ marginTop: theme.spacing.xl }}>
          Account security
        </AppText>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Change password"
          accessibilityHint="Opens the change password screen"
          onPress={() => router.push('/change-password' as Href)}
          style={({ pressed }) => [
            styles.row,
            {
              minHeight: theme.minTouchTarget,
              paddingVertical: theme.spacing.md,
              gap: theme.spacing.md,
              borderBottomColor: theme.colors.border,
            },
            pressed && styles.pressed,
          ]}>
          <Ionicons name="key-outline" size={20} color={theme.colors.textPrimary} />
          <View style={styles.text}>
            <AppText variant="bodyStrong">Change password</AppText>
            <AppText variant="small" color="textSecondary">
              Signs you out on your other devices
            </AppText>
          </View>
          <Ionicons name="chevron-forward" size={20} color={theme.colors.textSecondary} />
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1 },
  text: { flex: 1, gap: 2 },
  pressed: { opacity: 0.7 },
});
