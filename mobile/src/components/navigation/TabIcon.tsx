import React from 'react';
import { Ionicons } from '@expo/vector-icons';

export type TabDestination = 'home' | 'groups' | 'activity' | 'profile' | 'analytics' | 'budgets';

export interface TabIconProps {
  name: TabDestination;
  focused: boolean;
  color: string;
  size?: number;
}

const ICON_MAP: Record<TabDestination, { active: keyof typeof Ionicons.glyphMap; inactive: keyof typeof Ionicons.glyphMap }> = {
  home: { active: 'home', inactive: 'home-outline' },
  groups: { active: 'people', inactive: 'people-outline' },
  activity: { active: 'time', inactive: 'time-outline' },
  profile: { active: 'person', inactive: 'person-outline' },
  analytics: { active: 'pie-chart', inactive: 'pie-chart-outline' },
  budgets: { active: 'wallet', inactive: 'wallet-outline' },
};

export function TabIcon({ name, focused, color, size = 20 }: TabIconProps) {
  const iconConfig = ICON_MAP[name] ?? ICON_MAP.home;
  const glyph = focused ? iconConfig.active : iconConfig.inactive;
  return <Ionicons name={glyph} size={size} color={color} />;
}
