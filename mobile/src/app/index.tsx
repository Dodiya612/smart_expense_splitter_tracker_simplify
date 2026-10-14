import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';

export default function IndexScreen() {
  const theme = useTheme();

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.background }]}>
      {/* TEMPORARY: Minimal placeholder text to verify Inter font and theme color in Phase 0 */}
      <Text
        style={{
          fontFamily: theme.fontFamily.regular,
          color: theme.colors.textPrimary,
          fontSize: theme.typography.body.fontSize,
        }}>
        Smart Expense Splitter
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
