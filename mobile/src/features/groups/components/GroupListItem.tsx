import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { GroupSummary } from '../types';
import { groupTypeInfo, isAdminRole, memberCountLabel } from '../utils/groupDisplay';

export interface GroupListItemProps {
  group: GroupSummary;
  onPress: (group: GroupSummary) => void;
}

/** One row in the Groups list (T-29). */
export function GroupListItem({ group, onPress }: GroupListItemProps) {
  const theme = useTheme();
  const type = groupTypeInfo(group.type);
  const admin = isAdminRole(group.currentUserRole);
  const meta = `${type.label} · ${memberCountLabel(group.memberCount)}${admin ? ' · Admin' : ''}`;

  return (
    <AppCard
      onPress={() => onPress(group)}
      accessibilityLabel={`${group.name}, ${meta}`}
      accessibilityHint="Opens the group">
      <View style={[styles.row, { gap: theme.spacing.md }]}>
        <View
          style={[
            styles.icon,
            {
              width: theme.minTouchTarget,
              height: theme.minTouchTarget,
              borderRadius: theme.radii.pill,
              backgroundColor: theme.colors.surfaceMuted,
            },
          ]}>
          <Ionicons name={type.icon} size={22} color={theme.colors.textPrimary} />
        </View>
        <View style={styles.text}>
          <AppText variant="bodyStrong" numberOfLines={1}>
            {group.name}
          </AppText>
          <AppText variant="caption" color="textSecondary" numberOfLines={1}>
            {meta}
          </AppText>
        </View>
        <Ionicons name="chevron-forward" size={20} color={theme.colors.textSecondary} />
      </View>
    </AppCard>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  icon: { alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1 },
});
