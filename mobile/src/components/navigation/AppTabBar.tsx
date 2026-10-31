import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomTabBarProps } from 'expo-router/tabs';
import { Href, router } from 'expo-router';
import { useTheme } from '@/theme';
import { TabBarAddButton } from './TabBarAddButton';
import { TabDestination, TabIcon } from './TabIcon';

const TAB_LABELS: Record<string, string> = {
  home: 'Home',
  groups: 'Groups',
  activity: 'Activity',
  profile: 'Profile',
};

export function AppTabBar({ state, navigation }: BottomTabBarProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const bottomOffset = Math.max(insets.bottom, theme.spacing.md);

  const handleTabPress = (route: (typeof state.routes)[number], isFocused: boolean) => {
    const event = navigation.emit({
      type: 'tabPress',
      target: route.key,
      canPreventDefault: true,
    });

    if (!isFocused && !event.defaultPrevented) {
      navigation.navigate(route.name);
    }
  };

  const handleAddPress = () => {
    router.push('/add-expense' as Href);
  };

  const renderTab = (route: (typeof state.routes)[number]) => {
    const isFocused = state.routes[state.index]?.key === route.key;
    const name = route.name as TabDestination;
    const label = TAB_LABELS[name] ?? route.name;
    const color = isFocused ? theme.colors.primary : theme.colors.textSecondary;

    return (
      <Pressable
        key={route.key}
        accessibilityRole="tab"
        accessibilityState={{ selected: isFocused }}
        accessibilityLabel={label}
        onPress={() => handleTabPress(route, isFocused)}
        style={[styles.tabButton, { minHeight: theme.minTouchTarget }]}>
        <View
          style={[
            styles.capsule,
            {
              backgroundColor: isFocused ? theme.colors.info.soft : 'transparent',
              borderRadius: theme.radii.pill,
              paddingHorizontal: theme.spacing.xs,
              paddingVertical: theme.spacing.xs,
            },
          ]}>
          <TabIcon name={name} focused={isFocused} color={color} size={18} />
          <Text
            numberOfLines={1}
            style={[
              styles.label,
              {
                color,
                fontFamily: isFocused ? theme.fontFamily.semibold : theme.fontFamily.medium,
              },
            ]}>
            {label}
          </Text>
        </View>
      </Pressable>
    );
  };

  const homeRoute = state.routes.find((r) => r.name === 'home');
  const groupsRoute = state.routes.find((r) => r.name === 'groups');
  const activityRoute = state.routes.find((r) => r.name === 'activity');
  const profileRoute = state.routes.find((r) => r.name === 'profile');

  return (
    <View
      pointerEvents="box-none"
      style={[
        styles.outerContainer,
        {
          bottom: bottomOffset,
          paddingHorizontal: theme.spacing.md,
        },
      ]}>
      <View
        style={[
          styles.bar,
          theme.shadows.floating,
          {
            backgroundColor: theme.colors.surface,
            borderRadius: theme.radii.pill,
            borderColor: theme.colors.border,
            borderWidth: 1,
            paddingVertical: theme.spacing.xs,
            paddingHorizontal: theme.spacing.xs,
          },
        ]}>
        {homeRoute && renderTab(homeRoute)}
        {groupsRoute && renderTab(groupsRoute)}
        <View style={styles.addSlot}>
          <TabBarAddButton onPress={handleAddPress} />
        </View>
        {activityRoute && renderTab(activityRoute)}
        {profileRoute && renderTab(profileRoute)}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  outerContainer: { position: 'absolute', left: 0, right: 0, alignItems: 'center' },
  bar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', width: '100%', maxWidth: 440 },
  tabButton: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  capsule: { alignItems: 'center', justifyContent: 'center', width: '100%', gap: 2 },
  label: { fontSize: 10, lineHeight: 12, textAlign: 'center' },
  addSlot: { alignItems: 'center', justifyContent: 'center', paddingHorizontal: 2 },
});
