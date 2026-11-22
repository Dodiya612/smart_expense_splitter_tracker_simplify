import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Href, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';

export interface GroupScreenHeaderProps {
  title: string;
  subtitle?: string;
}

/** Back button plus title for the group stack screens (T-29). */
export function GroupScreenHeader({ title, subtitle }: GroupScreenHeaderProps) {
  const theme = useTheme();

  const goBack = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)/groups' as Href);
  };

  return (
    <View style={[styles.row, { gap: theme.spacing.sm, paddingVertical: theme.spacing.sm }]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Go back"
        onPress={goBack}
        hitSlop={theme.spacing.xs}
        style={({ pressed }) => [
          styles.back,
          { minWidth: theme.minTouchTarget, minHeight: theme.minTouchTarget },
          pressed && styles.pressed,
        ]}>
        <Ionicons name="chevron-back" size={24} color={theme.colors.textPrimary} />
      </Pressable>
      <View style={styles.text}>
        <AppText variant="heading" numberOfLines={1} accessibilityRole="header">
          {title}
        </AppText>
        {subtitle ? (
          <AppText variant="caption" color="textSecondary" numberOfLines={1}>
            {subtitle}
          </AppText>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  back: { alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1 },
  pressed: { opacity: 0.6 },
});
