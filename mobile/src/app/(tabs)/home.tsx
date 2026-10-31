/**
 * Home tab – Dashboard shell placeholder (T-26, Vivek's task).
 *
 * This stub satisfies the router so redirects from auth and the tab bar work.
 * Replace the body with the real DashboardScreen when T-26 is implemented.
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';

export default function HomeTab() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[
        styles.root,
        {
          backgroundColor: theme.colors.background,
          paddingTop: insets.top + theme.spacing.xl,
          paddingHorizontal: theme.spacing.lg,
        },
      ]}
    >
      <AppText variant="title" color="textPrimary">
        Dashboard
      </AppText>
      <AppText variant="body" color="textSecondary" style={{ marginTop: 8 }}>
        Coming soon – T-26 (Vivek). Head to the Expenses tab to add, edit or
        delete expenses.
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
});
