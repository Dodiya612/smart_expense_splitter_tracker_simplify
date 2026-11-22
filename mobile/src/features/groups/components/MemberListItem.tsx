import React from 'react';
import { StyleSheet, View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { GroupMember } from '../types';
import { initials, isAdminRole } from '../utils/groupDisplay';

export interface MemberListItemProps {
  member: GroupMember;
  isCurrentUser: boolean;
}

/** One member row on the group screen (T-29). */
export function MemberListItem({ member, isCurrentUser }: MemberListItemProps) {
  const theme = useTheme();
  const admin = isAdminRole(member.role);
  const name = isCurrentUser ? `${member.name} (you)` : member.name;

  return (
    <View
      accessible
      accessibilityLabel={`${name}${admin ? ', admin' : ''}, ${member.email}`}
      style={[
        styles.row,
        {
          gap: theme.spacing.md,
          paddingVertical: theme.spacing.sm,
          minHeight: theme.minTouchTarget,
          borderBottomColor: theme.colors.border,
        },
      ]}>
      <View
        style={[
          styles.avatar,
          {
            width: theme.minTouchTarget,
            height: theme.minTouchTarget,
            borderRadius: theme.radii.pill,
            backgroundColor: theme.colors.surfaceMuted,
          },
        ]}>
        <AppText variant="bodyStrong">{initials(member.name)}</AppText>
      </View>
      <View style={styles.text}>
        <AppText variant="bodyStrong" numberOfLines={1}>
          {name}
        </AppText>
        <AppText variant="caption" color="textSecondary" numberOfLines={1}>
          {member.email}
        </AppText>
      </View>
      {admin ? (
        <View
          style={[
            styles.badge,
            {
              borderRadius: theme.radii.sm,
              paddingHorizontal: theme.spacing.sm,
              paddingVertical: theme.spacing.xs,
              backgroundColor: theme.colors.info.soft,
            },
          ]}>
          <AppText variant="caption" color="info">
            Admin
          </AppText>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', borderBottomWidth: StyleSheet.hairlineWidth },
  avatar: { alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1 },
  badge: { alignSelf: 'center' },
});
