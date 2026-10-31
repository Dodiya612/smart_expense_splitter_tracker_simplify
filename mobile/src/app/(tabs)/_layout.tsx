/**
 * Tabs layout – Sprint 1 shell.
 *
 * Tabs registered here:
 *   home        – Dashboard shell (T-26, Vivek's task – placeholder here)
 *   expenses    – Expense list with delete+undo (T-20)
 *
 * Additional tabs (groups, insights, etc.) are added in later sprints.
 */

import React from 'react';
import { Tabs } from 'expo-router';
import { useTheme } from '@/theme';

export default function TabsLayout() {
  const theme = useTheme();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.colors.primary,
        tabBarInactiveTintColor: theme.colors.textSecondary,
        tabBarStyle: {
          backgroundColor: theme.colors.surface,
          borderTopColor: theme.colors.border,
        },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{
          title: 'Home',
          tabBarAccessibilityLabel: 'Home tab',
        }}
      />
      <Tabs.Screen
        name="expenses"
        options={{
          title: 'Expenses',
          tabBarAccessibilityLabel: 'Expenses tab',
        }}
      />
    </Tabs>
  );
}
