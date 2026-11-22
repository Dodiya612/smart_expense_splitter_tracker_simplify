/**
 * Create group (T-29 / US-17): name, optional description, and type (FR-14).
 * On success, opens the new group where the admin can share the invite code.
 */

import React from 'react';
import { View } from 'react-native';
import { Href, router } from 'expo-router';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { useTheme } from '@/theme';
import { GroupScreenHeader } from '../components/GroupScreenHeader';
import { GroupTypePicker } from '../components/GroupTypePicker';
import { useCreateGroup } from '../hooks/useCreateGroup';
import { GROUP_DESCRIPTION_MAX_LENGTH, GROUP_NAME_MAX_LENGTH } from '../utils/validation';

export function CreateGroupScreen() {
  const theme = useTheme();
  const form = useCreateGroup();

  const handleSubmit = async () => {
    const group = await form.submit();
    if (group) {
      router.replace({ pathname: '/groups/[id]', params: { id: group.id } } as Href);
    }
  };

  return (
    <ScreenContainer scrollable>
      <GroupScreenHeader title="Create group" />
      <View style={{ gap: theme.spacing.lg, marginTop: theme.spacing.sm }}>
        <AppInput
          label="Group name"
          placeholder="e.g. Flat 302"
          value={form.values.name}
          onChangeText={form.setName}
          error={form.fieldErrors.name}
          maxLength={GROUP_NAME_MAX_LENGTH}
          autoCapitalize="words"
          returnKeyType="next"
        />
        <AppInput
          label="Description (optional)"
          placeholder="What is this group for?"
          value={form.values.description}
          onChangeText={form.setDescription}
          error={form.fieldErrors.description}
          maxLength={GROUP_DESCRIPTION_MAX_LENGTH}
          multiline
        />
        <GroupTypePicker value={form.values.type} onChange={form.setType} error={form.fieldErrors.type} />
        {form.submitError ? (
          <AppText variant="small" color="negative" accessibilityRole="alert">
            {`[!] ${form.submitError.message}`}
          </AppText>
        ) : null}
        <Button
          label="Create group"
          fullWidth
          loading={form.isSubmitting}
          onPress={handleSubmit}
        />
      </View>
    </ScreenContainer>
  );
}
