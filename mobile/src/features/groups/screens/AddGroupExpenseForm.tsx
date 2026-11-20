import React, { useMemo } from 'react';
import { View } from 'react-native';
import { Href, router } from 'expo-router';
import { AppInput } from '@/components/ui/AppInput';
import { AppText } from '@/components/ui/AppText';
import { Button } from '@/components/ui/Button';
import { ScreenContainer } from '@/components/ui/ScreenContainer';
import { useTheme } from '@/theme';
import { ChoiceChips } from '../components/ChoiceChips';
import { GroupScreenHeader } from '../components/GroupScreenHeader';
import { SplitEditor } from '../components/SplitEditor';
import { useAddGroupExpense } from '../hooks/useAddGroupExpense';
import type { GroupDetail } from '../types';
import { GROUP_EXPENSE_CATEGORIES } from '../utils/groupCategories';
import { DESCRIPTION_MAX_LENGTH, NOTES_MAX_LENGTH } from '../utils/groupExpenseForm';

export interface AddGroupExpenseFormProps {
  group: GroupDetail;
  currentUserId?: string;
}

/** The loaded form for AddGroupExpenseScreen (T-31). */
export function AddGroupExpenseForm({ group, currentUserId }: AddGroupExpenseFormProps) {
  const theme = useTheme();
  const memberIds = useMemo(() => group.members.map((m) => m.userId), [group.members]);
  const form = useAddGroupExpense(group.id, memberIds, currentUserId);
  const payerOptions = group.members.map((m) => ({
    id: m.userId,
    label: m.userId === currentUserId ? 'You' : m.name,
  }));

  const handleSave = async () => {
    const saved = await form.save();
    if (saved) {
      router.replace({
        pathname: '/group-balances',
        params: { groupId: group.id, groupName: group.name },
      } as Href);
    }
  };

  return (
    <ScreenContainer scrollable>
      <GroupScreenHeader title="Add group expense" subtitle={group.name} />
      <View style={{ gap: theme.spacing.lg, marginTop: theme.spacing.sm }}>
        <AppInput
          label="Total amount (₹)"
          placeholder="e.g. 3000"
          value={form.values.amountText}
          onChangeText={(t) => form.setText('amountText', t)}
          error={form.fieldErrors.amountText}
          keyboardType="decimal-pad"
        />
        <AppInput
          label="What was it for?"
          placeholder="e.g. Groceries for the week"
          value={form.values.description}
          onChangeText={(t) => form.setText('description', t)}
          error={form.fieldErrors.description}
          maxLength={DESCRIPTION_MAX_LENGTH}
        />
        <ChoiceChips
          label="Category"
          options={GROUP_EXPENSE_CATEGORIES}
          selectedId={form.values.categoryId}
          onSelect={form.setCategory}
          error={form.fieldErrors.categoryId}
        />
        <ChoiceChips
          label="Who paid?"
          options={payerOptions}
          selectedId={form.values.payerId}
          onSelect={form.setPayer}
          error={form.fieldErrors.payerId}
        />
        <SplitEditor
          members={group.members}
          currentUserId={currentUserId}
          mode={form.values.mode}
          participantIds={form.values.participantIds}
          values={form.values.splitValues[form.values.mode]}
          preview={form.preview}
          onModeChange={form.setMode}
          onToggleParticipant={form.toggleParticipant}
          onChangeValue={form.setSplitValue}
        />
        <AppInput
          label="Notes (optional)"
          value={form.values.notes}
          onChangeText={(t) => form.setText('notes', t)}
          error={form.fieldErrors.notes}
          maxLength={NOTES_MAX_LENGTH}
          multiline
        />
        {form.submitError ? (
          <AppText variant="small" color="negative" accessibilityRole="alert">
            {`[!] ${form.submitError}`}
          </AppText>
        ) : null}
        <Button
          label="Save expense"
          fullWidth
          loading={form.isSaving}
          disabled={!form.preview.isBalanced}
          accessibilityHint={form.preview.isBalanced ? undefined : 'Make the split add up to the total first'}
          onPress={handleSave}
        />
        {!form.preview.isBalanced ? (
          <AppText variant="caption" color="textSecondary" style={{ textAlign: 'center' }}>
            Save turns on when the split adds up to the total.
          </AppText>
        ) : null}
      </View>
    </ScreenContainer>
  );
}
