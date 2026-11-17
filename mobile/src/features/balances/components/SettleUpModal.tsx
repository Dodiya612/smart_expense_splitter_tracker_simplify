/**
 * SettleUpModal component (T-33 / US-10).
 *
 * Settle sheet allowing:
 * - Full or partial settlement amount entry.
 * - Payment method selection (UPI, Cash, Bank Transfer).
 * - Optional notes for reference.
 * - Reminder toggle with local state (isolated for future T-36 integration).
 * - Immediate balance refresh via callback.
 */

import React, { useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { useTheme } from '@/theme';
import type { PeerStanding } from '../hooks/useGroupBalances';
import type { SettlementCreatePayload } from '../types';
import { formatInr } from './NetPositionCard';

export interface SettleUpModalProps {
  visible: boolean;
  counterparty: PeerStanding | null;
  currentUserId?: string;
  isCurrentUserPayer: boolean; // true if current user owes money; false if counterparty owes current user
  onClose: () => void;
  onSubmit: (payload: SettlementCreatePayload) => Promise<void>;
  isSubmitting: boolean;
  error: Error | null;
}

const PAYMENT_METHODS = [
  { id: 'upi', label: 'UPI' },
  { id: 'cash', label: 'Cash' },
  { id: 'bank_transfer', label: 'Bank Transfer' },
] as const;

export function SettleUpModal({
  visible,
  counterparty,
  currentUserId,
  isCurrentUserPayer,
  onClose,
  onSubmit,
  isSubmitting,
  error,
}: SettleUpModalProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  const outstandingPaise = counterparty ? Math.abs(counterparty.netAmountPaise) : 0;
  const initialRupees = (outstandingPaise / 100).toFixed(2);

  const [amountInput, setAmountInput] = useState<string>(initialRupees);
  const [isFullSettlement, setIsFullSettlement] = useState<boolean>(true);
  const [paymentMethod, setPaymentMethod] = useState<string>('upi');
  const [notes, setNotes] = useState<string>('');
  const [sendReminder, setSendReminder] = useState<boolean>(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Sync initial amount when counterparty changes
  React.useEffect(() => {
    if (counterparty) {
      const amt = (Math.abs(counterparty.netAmountPaise) / 100).toFixed(2);
      setAmountInput(amt);
      setIsFullSettlement(true);
      setValidationError(null);
      setNotes('');
      setSendReminder(false);
    }
  }, [counterparty]);

  const handleAmountChange = (text: string) => {
    setAmountInput(text);
    const parsed = parseFloat(text);
    if (!isNaN(parsed) && Math.round(parsed * 100) === outstandingPaise) {
      setIsFullSettlement(true);
    } else {
      setIsFullSettlement(false);
    }
    setValidationError(null);
  };

  const handleFullSettlementToggle = (full: boolean) => {
    setIsFullSettlement(full);
    if (full) {
      setAmountInput((outstandingPaise / 100).toFixed(2));
    }
  };

  const handleConfirm = async () => {
    if (!counterparty || !currentUserId) return;

    const parsedRupees = parseFloat(amountInput);
    if (isNaN(parsedRupees) || parsedRupees <= 0) {
      setValidationError('Please enter a valid amount greater than zero.');
      return;
    }

    const enteredPaise = Math.round(parsedRupees * 100);
    if (enteredPaise > outstandingPaise) {
      setValidationError(
        `Amount cannot exceed the total outstanding balance of ${formatInr(outstandingPaise)}.`
      );
      return;
    }

    setValidationError(null);

    const payerId = isCurrentUserPayer ? currentUserId : counterparty.userId;
    const payeeId = isCurrentUserPayer ? counterparty.userId : currentUserId;

    const payload: SettlementCreatePayload = {
      payerId,
      payeeId,
      amountPaise: enteredPaise,
      isFullSettlement: isFullSettlement && enteredPaise === outstandingPaise,
      paymentMethod,
      notes: notes.trim() || undefined,
      settlementDate: new Date().toISOString().slice(0, 10),
      sendReminder,
    };

    try {
      await onSubmit(payload);
      onClose();
    } catch {
      // Handled by parent error state
    }
  };

  if (!visible || !counterparty) return null;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={[styles.backdrop, { backgroundColor: theme.colors.overlay }]}>
        <View
          style={[
            styles.sheet,
            {
              backgroundColor: theme.colors.surface,
              borderTopLeftRadius: theme.radii.xl,
              borderTopRightRadius: theme.radii.xl,
              paddingBottom: Math.max(insets.bottom, theme.spacing.lg),
              maxHeight: '85%',
            },
          ]}
        >
          {/* Header */}
          <View
            style={[
              styles.header,
              { borderBottomColor: theme.colors.border, padding: theme.spacing.md },
            ]}
          >
            <View>
              <AppText variant="heading" color="textPrimary">
                Record Settlement
              </AppText>
              <AppText variant="caption" color="textSecondary">
                {isCurrentUserPayer
                  ? `Settle your debt to ${counterparty.name}`
                  : `Record payment received from ${counterparty.name}`}
              </AppText>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Close settlement modal"
              onPress={onClose}
              hitSlop={8}
            >
              <Ionicons name="close" size={24} color={theme.colors.textSecondary} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={[styles.content, { padding: theme.spacing.md, gap: theme.spacing.md }]}>
            {/* Outstanding Summary banner */}
            <AppCard
              style={[
                styles.summaryCard,
                {
                  backgroundColor: theme.colors.surfaceMuted,
                  borderColor: theme.colors.border,
                  padding: theme.spacing.md,
                },
              ]}
            >
              <AppText variant="caption" color="textSecondary">
                Outstanding Balance
              </AppText>
              <AppText
                variant="heading"
                style={{
                  color: isCurrentUserPayer
                    ? theme.colors.negative.text
                    : theme.colors.positive.text,
                  marginTop: 2,
                }}
              >
                {formatInr(outstandingPaise)}
              </AppText>
            </AppCard>

            {/* Settlement Type Selector */}
            <View style={{ gap: theme.spacing.xs }}>
              <AppText variant="bodyStrong" color="textPrimary">
                Settlement Type
              </AppText>
              <View style={styles.segmentContainer}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Full settlement"
                  onPress={() => handleFullSettlementToggle(true)}
                  style={[
                    styles.segmentButton,
                    {
                      borderColor: isFullSettlement ? theme.colors.primary : theme.colors.border,
                      backgroundColor: isFullSettlement ? theme.colors.primary : theme.colors.surface,
                      borderRadius: theme.radii.sm,
                      minHeight: theme.minTouchTarget,
                    },
                  ]}
                >
                  <AppText
                    variant="caption"
                    style={{
                      color: isFullSettlement ? theme.colors.textOnPrimary : theme.colors.textPrimary,
                      fontFamily: theme.fontFamily.semibold,
                    }}
                  >
                    Full ({formatInr(outstandingPaise)})
                  </AppText>
                </Pressable>

                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Partial settlement"
                  onPress={() => handleFullSettlementToggle(false)}
                  style={[
                    styles.segmentButton,
                    {
                      borderColor: !isFullSettlement ? theme.colors.primary : theme.colors.border,
                      backgroundColor: !isFullSettlement ? theme.colors.primary : theme.colors.surface,
                      borderRadius: theme.radii.sm,
                      minHeight: theme.minTouchTarget,
                    },
                  ]}
                >
                  <AppText
                    variant="caption"
                    style={{
                      color: !isFullSettlement ? theme.colors.textOnPrimary : theme.colors.textPrimary,
                      fontFamily: theme.fontFamily.semibold,
                    }}
                  >
                    Partial Amount
                  </AppText>
                </Pressable>
              </View>
            </View>

            {/* Amount Input */}
            <AppInput
              label="Settlement Amount (₹)"
              placeholder="0.00"
              value={amountInput}
              onChangeText={handleAmountChange}
              keyboardType="decimal-pad"
              error={validationError || undefined}
              accessibilityLabel="Settlement amount in rupees"
            />

            {/* Payment Method Picker */}
            <View style={{ gap: theme.spacing.xs }}>
              <AppText variant="bodyStrong" color="textPrimary">
                Payment Channel
              </AppText>
              <View style={styles.methodsRow}>
                {PAYMENT_METHODS.map((method) => {
                  const isSelected = paymentMethod === method.id;
                  return (
                    <Pressable
                      key={method.id}
                      accessibilityRole="radio"
                      accessibilityState={{ selected: isSelected }}
                      accessibilityLabel={`Payment method ${method.label}`}
                      onPress={() => setPaymentMethod(method.id)}
                      style={[
                        styles.methodChip,
                        {
                          borderColor: isSelected ? theme.colors.primary : theme.colors.border,
                          backgroundColor: isSelected ? theme.colors.info.soft : theme.colors.surface,
                          borderRadius: theme.radii.pill,
                          minHeight: theme.minTouchTarget,
                          paddingHorizontal: theme.spacing.md,
                        },
                      ]}
                    >
                      <Ionicons
                        name={
                          method.id === 'upi'
                            ? 'flash-outline'
                            : method.id === 'cash'
                              ? 'cash-outline'
                              : 'card-outline'
                        }
                        size={16}
                        color={isSelected ? theme.colors.primary : theme.colors.textSecondary}
                      />
                      <AppText
                        variant="caption"
                        style={{
                          color: isSelected ? theme.colors.primary : theme.colors.textSecondary,
                          fontFamily: isSelected ? theme.fontFamily.semibold : theme.fontFamily.medium,
                        }}
                      >
                        {method.label}
                      </AppText>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            {/* Optional Notes */}
            <AppInput
              label="Notes (Optional)"
              placeholder="e.g. Paid via Google Pay reference 1234"
              value={notes}
              onChangeText={setNotes}
              maxLength={200}
              accessibilityLabel="Optional settlement notes"
            />

            {/* Reminder Toggle (US-10 AC5, local state pending T-36) */}
            <View
              style={[
                styles.reminderRow,
                {
                  backgroundColor: theme.colors.surfaceMuted,
                  borderRadius: theme.radii.md,
                  padding: theme.spacing.sm,
                  borderColor: theme.colors.border,
                },
              ]}
            >
              <View style={{ flex: 1, paddingRight: theme.spacing.sm }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <Ionicons name="notifications-outline" size={16} color={theme.colors.primary} />
                  <AppText variant="bodyStrong" color="textPrimary">
                    Send Payment Reminder
                  </AppText>
                </View>
                <AppText variant="caption" color="textSecondary" style={{ marginTop: 2 }}>
                  Queue a notification to {counterparty.name} regarding this settlement.
                </AppText>
              </View>
              <Switch
                value={sendReminder}
                onValueChange={setSendReminder}
                accessibilityLabel="Toggle payment reminder notification"
                trackColor={{ false: theme.colors.border, true: theme.colors.primary }}
              />
            </View>

            {/* API Error Banner */}
            {error ? (
              <View
                style={[
                  styles.errorBanner,
                  {
                    backgroundColor: theme.colors.negative.soft,
                    borderColor: theme.colors.negative.fill,
                    borderRadius: theme.radii.sm,
                    padding: theme.spacing.sm,
                  },
                ]}
                accessibilityRole="alert"
              >
                <Ionicons name="alert-circle" size={16} color={theme.colors.negative.text} />
                <AppText variant="caption" style={{ color: theme.colors.negative.text, flex: 1 }}>
                  {error.message || 'Settlement failed. Please try again.'}
                </AppText>
              </View>
            ) : null}

            {/* Action Buttons */}
            <View style={[styles.actionButtons, { marginTop: theme.spacing.sm }]}>
              <Button
                label={isSubmitting ? 'Recording...' : 'Record Settlement'}
                variant="primary"
                fullWidth
                onPress={handleConfirm}
                disabled={isSubmitting}
                accessibilityLabel="Confirm and record settlement"
              />
              {isSubmitting ? (
                <ActivityIndicator
                  size="small"
                  color={theme.colors.primary}
                  style={{ marginTop: 8 }}
                />
              ) : null}
            </View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  sheet: {
    width: '100%',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: 1,
  },
  content: {
    paddingBottom: 20,
  },
  summaryCard: {
    borderWidth: 1,
    alignItems: 'center',
  },
  segmentContainer: {
    flexDirection: 'row',
    gap: 8,
  },
  segmentButton: {
    flex: 1,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
  },
  methodsRow: {
    flexDirection: 'row',
    gap: 8,
    flexWrap: 'wrap',
  },
  methodChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderWidth: 1,
    paddingVertical: 8,
  },
  reminderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
  },
  errorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderWidth: 1,
  },
  actionButtons: {
    gap: 8,
  },
});
