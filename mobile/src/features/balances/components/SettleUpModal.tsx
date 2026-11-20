/**
 * SettleUpModal component (T-33 / US-10).
 *
 * Settle sheet allowing:
 * - Full or partial settlement amount entry (integer paise, never above what is owed).
 * - Payment method selection (UPI, Cash, Bank Transfer).
 * - Optional notes for reference.
 * - Idempotency-Key: Retry of the same submission reuses the key; a changed one gets a new key.
 * - On failure the sheet keeps every value and shows the server's message with Retry.
 *
 * The parent remounts this component per counterparty (React `key`), so the
 * initial values come straight from props without a resetting effect.
 */

import React, { useRef, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { AppCard } from '@/components/ui/AppCard';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { newIdempotencyKey } from '@/features/expenses/services/expenseApi';
import type { ApiError } from '@/services/api/types';
import { useTheme } from '@/theme';
import { formatPaise, paiseToInputText, parseRupeesToPaise } from '@/utils/money';
import type { PeerStanding, SettlementCreatePayload, SettlementRecord } from '../types';
import {
  buildSettlementPayload,
  checkSettlementAmount,
  createSettlementKeyTracker,
  runSettlement,
} from '../utils/settlementSubmission';

export interface SettleUpModalProps {
  visible: boolean;
  counterparty: PeerStanding | null;
  currentUserId?: string;
  isCurrentUserPayer: boolean; // true if current user owes money; false if counterparty owes current user
  onClose: () => void;
  /** Saves (POST /settlements with the given key) and refreshes; throws on failure. */
  onSubmit: (payload: SettlementCreatePayload, idempotencyKey: string) => Promise<SettlementRecord>;
  onSaved: (saved: SettlementRecord) => void;
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
  onSaved,
}: SettleUpModalProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  const outstandingPaise = counterparty ? Math.abs(counterparty.netAmountPaise) : 0;

  const [amountInput, setAmountInput] = useState<string>(paiseToInputText(outstandingPaise));
  const [isFullSettlement, setIsFullSettlement] = useState<boolean>(true);
  const [paymentMethod, setPaymentMethod] = useState<string>('upi');
  const [notes, setNotes] = useState<string>('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<ApiError | null>(null);
  const keyTracker = useRef(createSettlementKeyTracker(newIdempotencyKey));

  const handleAmountChange = (text: string) => {
    setAmountInput(text);
    setIsFullSettlement(parseRupeesToPaise(text) === outstandingPaise);
    setValidationError(null);
    setError(null);
  };

  const handleFullSettlementToggle = (full: boolean) => {
    setIsFullSettlement(full);
    if (full) {
      setAmountInput(paiseToInputText(outstandingPaise));
    }
    setValidationError(null);
  };

  const handleConfirm = async () => {
    if (!counterparty || !currentUserId || isSubmitting) return;

    const check = checkSettlementAmount(amountInput, outstandingPaise);
    if (!check.ok) {
      setValidationError(check.message);
      return;
    }
    setValidationError(null);

    const payload = buildSettlementPayload({
      payerId: isCurrentUserPayer ? currentUserId : counterparty.userId,
      payeeId: isCurrentUserPayer ? counterparty.userId : currentUserId,
      amountPaise: check.amountPaise,
      outstandingPaise,
      paymentMethod,
      notes,
    });

    setIsSubmitting(true);
    setError(null);
    // Values are only read here; on failure every field stays as typed.
    const outcome = await runSettlement(payload, keyTracker.current, onSubmit);
    setIsSubmitting(false);
    if (outcome.ok) {
      keyTracker.current.reset();
      onSaved(outcome.saved);
      onClose();
    } else {
      setError(outcome.error);
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
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={[styles.backdrop, { backgroundColor: theme.colors.overlay }]}
      >
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
                Record settlement
              </AppText>
              <AppText variant="caption" color="textSecondary">
                {isCurrentUserPayer
                  ? `Record that you settled with ${counterparty.name}`
                  : `Record that ${counterparty.name} settled with you`}
              </AppText>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Close settlement modal"
              onPress={onClose}
              style={[styles.closeButton, { minWidth: theme.minTouchTarget, minHeight: theme.minTouchTarget }]}
            >
              <Ionicons name="close" size={24} color={theme.colors.textSecondary} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: theme.spacing.xl, gap: theme.spacing.md }}>
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
                Owed now
              </AppText>
              <AppText
                variant="heading"
                style={{
                  color: isCurrentUserPayer
                    ? theme.colors.negative.text
                    : theme.colors.positive.text,
                  marginTop: theme.spacing.xs,
                }}
              >
                {formatPaise(outstandingPaise)}
              </AppText>
            </AppCard>

            {/* Settlement Type Selector */}
            <View style={{ gap: theme.spacing.xs }}>
              <AppText variant="bodyStrong" color="textPrimary">
                Amount to settle
              </AppText>
              <View style={[styles.segmentContainer, { gap: theme.spacing.sm }]}>
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
                      paddingVertical: theme.spacing.sm,
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
                    Full ({formatPaise(outstandingPaise)})
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
                      paddingVertical: theme.spacing.sm,
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
                    Part of it
                  </AppText>
                </Pressable>
              </View>
            </View>

            {/* Amount Input */}
            <AppInput
              label="Amount (₹)"
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
                How it was paid
              </AppText>
              <View style={[styles.methodsRow, { gap: theme.spacing.sm }]}>
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
                          paddingVertical: theme.spacing.sm,
                          gap: theme.spacing.sm,
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
              label="Notes (optional)"
              placeholder="e.g. Paid via Google Pay reference 1234"
              value={notes}
              onChangeText={setNotes}
              maxLength={200}
              accessibilityLabel="Optional settlement notes"
            />

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
                    gap: theme.spacing.sm,
                  },
                ]}
                accessibilityRole="alert"
              >
                <View style={[styles.errorTextRow, { gap: theme.spacing.sm }]}>
                  <Ionicons name="alert-circle" size={16} color={theme.colors.negative.text} />
                  <AppText variant="caption" style={{ color: theme.colors.negative.text, flex: 1 }}>
                    {`[!] ${error.message || 'Could not record the settlement. Please try again.'}`}
                  </AppText>
                </View>
                {error.isRetryable ? (
                  <Button
                    label="Try again"
                    variant="outline"
                    onPress={handleConfirm}
                    disabled={isSubmitting}
                    accessibilityLabel="Try recording this settlement again"
                  />
                ) : null}
              </View>
            ) : null}

            {/* Action Buttons */}
            <View style={{ marginTop: theme.spacing.sm, gap: theme.spacing.sm }}>
              <Button
                label={isSubmitting ? 'Recording…' : 'Record settlement'}
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
                  style={{ marginTop: theme.spacing.sm }}
                />
              ) : null}
            </View>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
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
  closeButton: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: 1,
  },
  summaryCard: {
    borderWidth: 1,
    alignItems: 'center',
  },
  segmentContainer: {
    flexDirection: 'row',
  },
  segmentButton: {
    flex: 1,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  methodsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  methodChip: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
  },
  errorBanner: {
    borderWidth: 1,
  },
  errorTextRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
});
