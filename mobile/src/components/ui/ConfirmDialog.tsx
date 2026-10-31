/**
 * ConfirmDialog – generic accessible confirmation bottom-sheet.
 *
 * Used by T-20 (Delete with confirm and undo, US-08) and reusable across the
 * app wherever a destructive action needs confirmation.
 *
 * Props:
 *   visible       – controls Modal visibility
 *   title         – bold heading (e.g. "Delete expense?")
 *   message       – explanatory body text
 *   confirmLabel  – label for the destructive confirm button (default "Delete")
 *   cancelLabel   – label for the cancel button (default "Cancel")
 *   onConfirm     – called when the user confirms
 *   onCancel      – called when the user cancels or taps the backdrop
 *   isLoading     – disables both buttons while the API call is in flight
 */

import React from 'react';
import {
  Modal,
  Pressable,
  StyleSheet,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AppText } from './AppText';
import { Button } from './Button';
import { useTheme } from '@/theme';

export interface ConfirmDialogProps {
  visible: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading?: boolean;
}

export function ConfirmDialog({
  visible,
  title,
  message,
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
  isLoading = false,
}: ConfirmDialogProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onCancel}
      statusBarTranslucent
    >
      {/* ── Backdrop ─────────────────────────────────────────────── */}
      <Pressable
        style={[styles.backdrop, { backgroundColor: theme.colors.overlay }]}
        accessibilityRole="button"
        accessibilityLabel="Dismiss dialog"
        onPress={isLoading ? undefined : onCancel}
      >
        {/* ── Sheet – swallow taps so backdrop Pressable doesn't fire ── */}
        <Pressable
          onPress={() => {}}
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
          ]}
          accessibilityViewIsModal
          importantForAccessibility="yes"
        >
          <AppText variant="heading" color="textPrimary" style={styles.title}>
            {title}
          </AppText>

          <AppText variant="body" color="textSecondary">
            {message}
          </AppText>

          <View style={[styles.actions, { gap: theme.spacing.sm }]}>
            <Button
              label={confirmLabel}
              variant="destructive"
              fullWidth
              loading={isLoading}
              disabled={isLoading}
              onPress={onConfirm}
              accessibilityLabel={confirmLabel}
            />
            <Button
              label={cancelLabel}
              variant="outline"
              fullWidth
              disabled={isLoading}
              onPress={onCancel}
              accessibilityLabel={cancelLabel}
            />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    paddingBottom: 16,
  },
  sheet: {
    width: '100%',
  },
  title: {
    textAlign: 'center',
  },
  actions: {
    marginTop: 8,
  },
});
