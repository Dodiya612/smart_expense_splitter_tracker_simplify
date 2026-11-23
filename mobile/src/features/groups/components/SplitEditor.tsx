import React from 'react';
import { View } from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { useTheme } from '@/theme';
import type { SplitMode, SplitPreview } from '@/utils/splits';
import type { GroupMember } from '../types';
import { SplitModeTabs } from './SplitModeTabs';
import { SplitParticipantRow } from './SplitParticipantRow';
import { SplitSummary } from './SplitSummary';

export interface SplitEditorProps {
  members: GroupMember[];
  currentUserId?: string;
  mode: SplitMode;
  participantIds: string[];
  values: Record<string, string>;
  preview: SplitPreview;
  onModeChange: (mode: SplitMode) => void;
  onToggleParticipant: (userId: string) => void;
  onChangeValue: (userId: string, text: string) => void;
}

/**
 * Split editor (T-31 / US-19): equal, exact, percentage or parts, with a live
 * preview of each share and what is left to assign. Rows are mapped, not a
 * FlatList, because the editor sits inside the form's ScrollView and a group
 * has only a handful of members.
 */
export function SplitEditor(props: SplitEditorProps) {
  const { members, currentUserId, mode, participantIds, values, preview } = props;
  const theme = useTheme();
  const included = new Set(participantIds);
  const approximate = mode === 'percentage' && !preview.isBalanced;

  return (
    <View style={{ gap: theme.spacing.md }}>
      <AppText variant="small">Split</AppText>
      <SplitModeTabs mode={mode} onChange={props.onModeChange} />
      <SplitSummary mode={mode} preview={preview} />
      <View>
        {members.map((member) => (
          <SplitParticipantRow
            key={member.userId}
            name={member.userId === currentUserId ? `${member.name} (you)` : member.name}
            included={included.has(member.userId)}
            mode={mode}
            value={values[member.userId] ?? ''}
            sharePaise={preview.shares[member.userId] ?? null}
            approximate={approximate}
            error={preview.fieldErrors[member.userId]}
            onToggle={() => props.onToggleParticipant(member.userId)}
            onChangeValue={(text) => props.onChangeValue(member.userId, text)}
          />
        ))}
      </View>
    </View>
  );
}
