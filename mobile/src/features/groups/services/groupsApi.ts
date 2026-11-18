/**
 * Groups API service (T-29 / US-17).
 *
 * Calls the T-28 endpoints (see backend/app/api/v1/endpoints/groups.py):
 * - GET    /api/v1/groups                     list my groups
 * - POST   /api/v1/groups                     create (returns a one-time join code)
 * - GET    /api/v1/groups/:groupId            details + active members
 * - POST   /api/v1/groups/join                join with a code
 * - POST   /api/v1/groups/:groupId/join-code  new code (revokes the old one; admin only)
 * - DELETE /api/v1/groups/:groupId/join-code  revoke the active code (admin only)
 *
 * The backend sends camelCase; snake_case fallbacks are kept, matching balancesApi.ts.
 */

import { fastApiClient } from '@/services/api/fastApiClient';
import type {
  CreateGroupInput,
  GroupDetail,
  GroupMember,
  GroupSummary,
  JoinCode,
} from '../types';

type Raw = Record<string, unknown>;

function str(raw: Raw, camel: string, snake: string): string {
  const value = raw[camel] ?? raw[snake];
  return typeof value === 'string' ? value : '';
}

function optStr(raw: Raw, camel: string, snake: string): string | undefined {
  const value = raw[camel] ?? raw[snake];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

export function mapGroupSummary(raw: Raw): GroupSummary {
  const count = raw.memberCount ?? raw.member_count;
  return {
    id: str(raw, 'id', 'id'),
    name: str(raw, 'name', 'name'),
    description: optStr(raw, 'description', 'description'),
    type: str(raw, 'type', 'type'),
    createdBy: str(raw, 'createdBy', 'created_by'),
    createdAt: str(raw, 'createdAt', 'created_at'),
    memberCount: typeof count === 'number' ? count : 0,
    currentUserRole: str(raw, 'currentUserRole', 'current_user_role') || 'member',
  };
}

export function mapGroupMember(raw: Raw): GroupMember {
  return {
    userId: str(raw, 'userId', 'user_id'),
    name: str(raw, 'name', 'name'),
    email: str(raw, 'email', 'email'),
    role: str(raw, 'role', 'role') || 'member',
    status: str(raw, 'status', 'status'),
    joinedAt: str(raw, 'joinedAt', 'joined_at'),
  };
}

export function mapGroupDetail(raw: Raw): GroupDetail {
  const members = Array.isArray(raw.members) ? (raw.members as Raw[]) : [];
  return {
    id: str(raw, 'id', 'id'),
    name: str(raw, 'name', 'name'),
    description: optStr(raw, 'description', 'description'),
    type: str(raw, 'type', 'type'),
    createdBy: str(raw, 'createdBy', 'created_by'),
    createdAt: str(raw, 'createdAt', 'created_at'),
    members: members.map(mapGroupMember),
    currentUserRole: optStr(raw, 'currentUserRole', 'current_user_role'),
    joinCode: optStr(raw, 'joinCode', 'join_code'),
  };
}

export function mapJoinCode(raw: Raw): JoinCode {
  return {
    groupId: str(raw, 'groupId', 'group_id'),
    code: str(raw, 'code', 'code'),
    expiresAt: str(raw, 'expiresAt', 'expires_at'),
  };
}

export async function listGroups(): Promise<GroupSummary[]> {
  const list = await fastApiClient.get<Raw[]>('/api/v1/groups');
  return (Array.isArray(list) ? list : []).map(mapGroupSummary);
}

export async function getGroup(groupId: string): Promise<GroupDetail> {
  const raw = await fastApiClient.get<Raw>(`/api/v1/groups/${encodeURIComponent(groupId)}`);
  return mapGroupDetail(raw);
}

export async function createGroup(input: CreateGroupInput): Promise<GroupDetail> {
  const raw = await fastApiClient.post<Raw>('/api/v1/groups', {
    name: input.name,
    description: input.description,
    type: input.type,
  });
  return mapGroupDetail(raw);
}

export async function joinGroupByCode(code: string): Promise<GroupDetail> {
  const raw = await fastApiClient.post<Raw>('/api/v1/groups/join', { code });
  const group = (raw.group ?? {}) as Raw;
  return mapGroupDetail(group);
}

export async function rotateJoinCode(groupId: string): Promise<JoinCode> {
  const raw = await fastApiClient.post<Raw>(
    `/api/v1/groups/${encodeURIComponent(groupId)}/join-code`
  );
  return mapJoinCode(raw);
}

export async function revokeJoinCode(groupId: string): Promise<void> {
  await fastApiClient.delete<void>(`/api/v1/groups/${encodeURIComponent(groupId)}/join-code`);
}
