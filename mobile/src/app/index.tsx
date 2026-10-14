/* TEMPORARY: Showcase screen for Phase 1 primitives. Will be deleted when the login screen is built. */
import React, { useRef, useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';
import { useTheme } from '@/theme';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { AppInput } from '@/components/ui/AppInput';
import { ScreenContainer } from '@/components/ui/ScreenContainer';

export default function ShowcaseScreen() {
  const theme = useTheme();
  const passwordRef = useRef<TextInput>(null);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errorInput, setErrorInput] = useState('invalid-user');

  return (
    <ScreenContainer scrollable={true} contentContainerStyle={styles.content}>
      <AppText variant="display" color="textPrimary">
        Primitives
      </AppText>
      <AppText variant="body" color="textSecondary">
        Phase 1 component showcase
      </AppText>

      {/* Typography Variants */}
      <View style={[styles.section, { gap: theme.spacing.xs }]}>
        <AppText variant="title">Title text</AppText>
        <AppText variant="heading">Heading text</AppText>
        <AppText variant="body">Body regular text</AppText>
        <AppText variant="bodyStrong">Body strong text</AppText>
        <AppText variant="small">Small text</AppText>
        <AppText variant="caption">Caption text</AppText>
        <AppText variant="moneyLarge">₹12,450.00</AppText>
        <AppText variant="money">₹1,250.00</AppText>
      </View>

      {/* Text Colors */}
      <View style={[styles.section, { gap: theme.spacing.xs }]}>
        <AppText variant="bodyStrong" color="textPrimary">textPrimary</AppText>
        <AppText variant="bodyStrong" color="textSecondary">textSecondary</AppText>
        <AppText variant="bodyStrong" color="positive">+₹500.00 (positive)</AppText>
        <AppText variant="bodyStrong" color="negative">-₹250.00 (negative)</AppText>
        <AppText variant="bodyStrong" color="warning">Budget near limit (warning)</AppText>
        <AppText variant="bodyStrong" color="info">Transfer pending (info)</AppText>
        <View style={[styles.darkBox, { backgroundColor: theme.colors.primary, borderRadius: theme.radii.sm, padding: theme.spacing.xs }]}>
          <AppText variant="bodyStrong" color="textOnPrimary">textOnPrimary on dark</AppText>
        </View>
      </View>

      {/* Buttons */}
      <View style={[styles.section, { gap: theme.spacing.sm }]}>
        <Button label="Primary Button" variant="primary" fullWidth />
        <Button label="Secondary Button" variant="secondary" fullWidth />
        <Button label="Outline Button" variant="outline" fullWidth />
        <Button label="Destructive Button" variant="destructive" fullWidth />
        <Button label="Disabled Button" variant="primary" disabled fullWidth />
        <Button label="Loading Button" variant="primary" loading fullWidth />
        <Button label="Loading Destructive" variant="destructive" loading fullWidth />
      </View>

      {/* Inputs */}
      <View style={[styles.section, { gap: theme.spacing.md }]}>
        <AppInput
          label="Email address"
          value={email}
          onChangeText={setEmail}
          placeholder="name@example.com"
          keyboardType="email-address"
          autoCapitalize="none"
          returnKeyType="next"
          onSubmitEditing={() => passwordRef.current?.focus()}
          helperText="We'll never share your email"
        />
        <AppInput
          ref={passwordRef}
          label="Password"
          value={password}
          onChangeText={setPassword}
          placeholder="Enter password"
          secureTextEntry
          returnKeyType="done"
        />
        <AppInput
          label="Username with error"
          value={errorInput}
          onChangeText={setErrorInput}
          error="Username already taken"
        />
        <AppInput
          label="Disabled input"
          value="read-only-account"
          disabled
        />
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  content: {
    paddingBottom: 40,
    gap: 20,
  },
  section: {
    width: '100%',
  },
  darkBox: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
