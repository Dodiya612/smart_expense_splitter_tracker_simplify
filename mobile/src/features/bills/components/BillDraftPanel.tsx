/**
 * "Read from your bill" panel on the add-expense form (T-54 / US-16): the bill
 * photo, what needs checking, and the line items. Everything here is a draft;
 * the expense is saved only when the user taps "Confirm and save".
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { formatPaise } from '@/utils/money';
import type { BillDraft } from '../types';
import { generalWarnings, itemDetail } from '../utils/billDraft';
import { ReceiptImage } from './ReceiptImage';

export interface BillDraftPanelProps {
  draft: BillDraft;
}

export function BillDraftPanel({ draft }: BillDraftPanelProps) {
  const theme = useTheme();
  const warnings = generalWarnings(draft);
  const itemsNote =
    draft.itemsSource === 'llm'
      ? 'Items read with AI. Every price was checked against the bill text.'
      : 'Items read from the bill text.';

  return (
    <View
      style={[
        styles.panel,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.border,
          borderRadius: theme.radii.md,
          padding: theme.spacing.md,
          gap: theme.spacing.md,
        },
      ]}>
      <View style={{ gap: theme.spacing.xs }}>
        <AppText variant="bodyStrong" accessibilityRole="header">
          Read from your bill
        </AppText>
        <AppText variant="caption" color="textSecondary">
          Check the amount, date and category below, then confirm. Nothing is saved until you do.
        </AppText>
      </View>

      <ReceiptImage receiptId={draft.receiptId} height={180} />

      {warnings.length > 0 ? (
        <View
          accessibilityRole="alert"
          style={{
            backgroundColor: theme.colors.warning.soft,
            borderRadius: theme.radii.sm,
            padding: theme.spacing.sm,
            gap: theme.spacing.xs,
          }}>
          {warnings.map((w, i) => (
            <AppText key={`${w.code}-${i}`} variant="small" color="warning">
              {`[!] ${w.message}`}
            </AppText>
          ))}
        </View>
      ) : null}

      {draft.items.length > 0 ? (
        <View style={{ gap: theme.spacing.xs }}>
          <AppText variant="small">{`Items (${draft.items.length})`}</AppText>
          {draft.items.map((item, index) => {
            const detail = itemDetail(item, formatPaise);
            return (
              <View
                key={`${index}-${item.name}`}
                style={[styles.itemRow, { gap: theme.spacing.sm, borderBottomColor: theme.colors.border }]}
                accessible
                accessibilityLabel={`${item.name}, ${formatPaise(item.amountPaise)}`}>
                <View style={styles.flex}>
                  <AppText variant="small">{item.name}</AppText>
                  {detail ? (
                    <AppText variant="caption" color="textSecondary">
                      {detail}
                    </AppText>
                  ) : null}
                </View>
                <AppText variant="small">{formatPaise(item.amountPaise)}</AppText>
              </View>
            );
          })}
          <AppText variant="caption" color="textSecondary">
            {itemsNote}
          </AppText>
        </View>
      ) : (
        <AppText variant="caption" color="textSecondary">
          No line items could be read from this bill.
        </AppText>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    borderWidth: 1,
  },
  itemRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingVertical: 6,
  },
  flex: {
    flex: 1,
  },
});
