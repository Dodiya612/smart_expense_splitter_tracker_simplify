import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import { formatPaise } from '@/utils/money';
import type { SplitMode } from '@/utils/splits';

const INPUT_LABELS: Record<Exclude<SplitMode, 'equal'>, string> = {
  exact: 'Amount (₹)',
  percentage: 'Percent (%)',
  parts: 'Parts',
};

export interface SplitParticipantRowProps {
  name: string;
  included: boolean;
  mode: SplitMode;
  value: string;
  sharePaise: number | null;
  /** Percentage mode while unbalanced: the share is only a rough figure. */
  approximate: boolean;
  error?: string;
  onToggle: () => void;
  onChangeValue: (text: string) => void;
}

/** One person in the split editor: include tick, their input, and live share (T-31). */
export function SplitParticipantRow(props: SplitParticipantRowProps) {
  const { name, included, mode, value, sharePaise, approximate, error, onToggle, onChangeValue } = props;
  const theme = useTheme();
  const shareText = !included ? 'Not in this split' : sharePaise === null ? '—' : `${approximate ? 'about ' : ''}${formatPaise(sharePaise)}`;

  return (
    <View style={[styles.root, { gap: theme.spacing.xs, paddingVertical: theme.spacing.sm, borderBottomColor: theme.colors.border }]}>
      <View style={[styles.row, { gap: theme.spacing.sm }]}>
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked: included }}
          accessibilityLabel={`Include ${name}`}
          onPress={onToggle}
          style={({ pressed }) => [styles.row, styles.flex, { minHeight: theme.minTouchTarget, gap: theme.spacing.sm }, pressed && styles.pressed]}>
          <Ionicons
            name={included ? 'checkbox' : 'square-outline'}
            size={24}
            color={included ? theme.colors.primary : theme.colors.textSecondary}
          />
          <AppText variant="bodyStrong" numberOfLines={1} style={styles.flex}>
            {name}
          </AppText>
        </Pressable>
        <AppText
          variant={included ? 'money' : 'caption'}
          color={included ? 'textPrimary' : 'textSecondary'}
          accessibilityLabel={included ? `${name}'s share ${shareText}` : `${name} is not in this split`}>
          {shareText}
        </AppText>
      </View>
      {included && mode !== 'equal' ? (
        <AppInput
          label={INPUT_LABELS[mode]}
          accessibilityLabel={`${name}, ${INPUT_LABELS[mode]}`}
          value={value}
          onChangeText={onChangeValue}
          error={error}
          keyboardType={mode === 'parts' ? 'number-pad' : 'decimal-pad'}
          placeholder={mode === 'parts' ? '1' : '0'}
          returnKeyType="done"
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { borderBottomWidth: StyleSheet.hairlineWidth },
  row: { flexDirection: 'row', alignItems: 'center' },
  flex: { flex: 1 },
  pressed: { opacity: 0.7 },
});
