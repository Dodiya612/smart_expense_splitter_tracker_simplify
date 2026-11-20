import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { PasswordRequirement } from '../utils/changePassword';
import type { PasswordStrengthResult } from '../utils/passwordStrength';

export interface PasswordStrengthMeterProps {
  strength: PasswordStrengthResult;
  requirements: PasswordRequirement[];
}

type Tone = 'negative' | 'warning' | 'positive';

const toneFor = (score: number): Tone => (score <= 1 ? 'negative' : score === 2 ? 'warning' : 'positive');

/**
 * Real-time strength feedback for a new password (T-50): four bars for the 0-4 score,
 * a text label with the score (status is never shown by colour alone), the first hint,
 * and a checklist of the requirements with an icon per state.
 */
export function PasswordStrengthMeter({ strength, requirements }: PasswordStrengthMeterProps) {
  const theme = useTheme();
  const tone = toneFor(strength.score);
  const hint = strength.score < 3 ? strength.feedback[0] : undefined;

  return (
    <View style={{ gap: theme.spacing.xs }}>
      <View
        style={[styles.bars, { gap: theme.spacing.xs }]}
        accessible
        accessibilityRole="progressbar"
        accessibilityLabel={`Password strength ${strength.score} out of 4, ${strength.label}`}
        accessibilityValue={{ min: 0, max: 4, now: strength.score }}>
        {[1, 2, 3, 4].map((bar) => (
          <View
            key={bar}
            style={[
              styles.bar,
              { backgroundColor: bar <= strength.score ? theme.colors[tone].fill : theme.colors.border },
            ]}
          />
        ))}
      </View>
      <AppText variant="caption" color={tone} accessibilityLiveRegion="polite">
        {`Strength: ${strength.label} (${strength.score}/4)`}
      </AppText>
      {hint ? (
        <AppText variant="caption" color="textSecondary">
          {hint}
        </AppText>
      ) : null}
      <View style={{ gap: theme.spacing.xs, marginTop: theme.spacing.xs }}>
        {requirements.map((req) => (
          <View
            key={req.key}
            style={[styles.requirement, { gap: theme.spacing.xs }]}
            accessible
            accessibilityLabel={`${req.label}: ${req.met ? 'done' : 'not yet'}`}>
            <Ionicons
              name={req.met ? 'checkmark-circle-outline' : 'ellipse-outline'}
              size={16}
              color={req.met ? theme.colors.positive.text : theme.colors.textSecondary}
            />
            <AppText variant="caption" color={req.met ? 'positive' : 'textSecondary'}>
              {req.label}
            </AppText>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bars: { flexDirection: 'row', width: '100%' },
  bar: { flex: 1, height: 4, borderRadius: 2 },
  requirement: { flexDirection: 'row', alignItems: 'center' },
});
