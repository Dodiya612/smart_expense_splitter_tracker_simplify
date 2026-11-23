import React from 'react';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';

export interface LeaveGroupWarningProps {
  visible: boolean;
  title: string;
  message: string;
  isLeaving: boolean;
  onSettleUp: () => void;
  onLeaveAnyway: () => void;
  onCancel: () => void;
}

/**
 * Unsettled-balance warning shown before leaving (T-35 / US-22).
 * Like ConfirmDialog, plus a "Settle up first" shortcut as the main action.
 */
export function LeaveGroupWarning(props: LeaveGroupWarningProps) {
  const { visible, title, message, isLeaving, onSettleUp, onLeaveAnyway, onCancel } = props;
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel} statusBarTranslucent>
      <Pressable
        style={[styles.backdrop, { backgroundColor: theme.colors.overlay, paddingBottom: theme.spacing.lg }]}
        accessibilityRole="button"
        accessibilityLabel="Dismiss warning"
        onPress={isLeaving ? undefined : onCancel}>
        <Pressable
          onPress={() => {}}
          accessibilityViewIsModal
          style={[
            styles.sheet,
            {
              backgroundColor: theme.colors.surface,
              borderRadius: theme.radii.xl,
              padding: theme.spacing.xl,
              paddingBottom: Math.max(theme.spacing.xl, insets.bottom + theme.spacing.lg),
              marginHorizontal: theme.spacing.lg,
              gap: theme.spacing.md,
            },
          ]}>
          <View style={[styles.titleRow, { gap: theme.spacing.sm }]}>
            <Ionicons name="warning-outline" size={24} color={theme.colors.warning.text} />
            <AppText variant="heading" accessibilityRole="alert">
              {title}
            </AppText>
          </View>
          <AppText variant="body" color="textSecondary">
            {message}
          </AppText>
          <View style={{ gap: theme.spacing.sm, marginTop: theme.spacing.sm }}>
            <Button label="Settle up first" fullWidth disabled={isLeaving} onPress={onSettleUp} />
            <Button label="Leave anyway" variant="destructive" fullWidth loading={isLeaving} onPress={onLeaveAnyway} />
            <Button label="Cancel" variant="outline" fullWidth disabled={isLeaving} onPress={onCancel} />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end' },
  sheet: { width: '100%' },
  titleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
});
