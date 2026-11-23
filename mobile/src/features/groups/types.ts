/**
 * Group types for the groups feature (T-29 / US-17).
 * Aligned with backend/app/schemas/group.py (camelCase on the wire).
 */

export const GROUP_TYPES = ['friends', 'flat', 'trip', 'family'] as const;
export type GroupType = (typeof GROUP_TYPES)[number];

export type GroupRole = 'admin' | 'member' | string;

export interface GroupSummary {
  id: string;
  name: string;
  description?: string;
  type: string;
  createdBy: string;
  createdAt: string;
  memberCount: number;
  currentUserRole: GroupRole;
}

export interface GroupMember {
  userId: string;
  name: string;
  email: string;
  role: GroupRole;
  status: string;
  joinedAt: string;
}

export interface GroupDetail {
  id: string;
  name: string;
  description?: string;
  type: string;
  createdBy: string;
  createdAt: string;
  members: GroupMember[];
  currentUserRole?: GroupRole;
  /** Only present right after creating a group; the server keeps just a hash. */
  joinCode?: string;
}

export interface JoinCode {
  groupId: string;
  code: string;
  expiresAt: string;
}

export interface CreateGroupInput {
  name: string;
  description?: string;
  type: GroupType;
}
