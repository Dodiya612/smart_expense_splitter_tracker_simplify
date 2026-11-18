/**
 * Display helpers for groups (T-29 / US-17). Pure; unit-tested.
 */

import type { GroupType } from '../types';

export type GroupIconName = 'people-outline' | 'home-outline' | 'airplane-outline' | 'heart-outline';

const TYPE_INFO: Record<GroupType, { label: string; icon: GroupIconName }> = {
  friends: { label: 'Friends', icon: 'people-outline' },
  flat: { label: 'Flat', icon: 'home-outline' },
  trip: { label: 'Trip', icon: 'airplane-outline' },
  family: { label: 'Family', icon: 'heart-outline' },
};

export function groupTypeInfo(type: string): { label: string; icon: GroupIconName } {
  return TYPE_INFO[type as GroupType] ?? TYPE_INFO.friends;
}

export function memberCountLabel(count: number): string {
  return count === 1 ? '1 member' : `${count} members`;
}

/** Up to two initials for an avatar, e.g. "Harshul Patel" -> "HP". */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0].charAt(0);
  const last = parts.length > 1 ? parts[parts.length - 1].charAt(0) : '';
  return (first + last).toUpperCase();
}

export function isAdminRole(role: string | undefined): boolean {
  return role === 'admin' || role === 'owner';
}
