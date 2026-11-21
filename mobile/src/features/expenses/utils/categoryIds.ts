/**
 * Form category <-> server category id (T-45, finishing T-19).
 *
 * The expense form keeps short ids such as 'food' (CATEGORIES in ../types), but
 * the backend stores category UUIDs. There is no categories endpoint yet, so this
 * maps the form ids to the 12 default categories seeded with fixed ids by
 * backend/alembic/versions/004_create_expenses_and_categories.py (the same list
 * as features/groups/utils/groupCategories.ts). Replace with an API call once
 * GET /api/v1/categories exists.
 */

const SEEDED = (n: number): string => `00000000-0000-4000-8000-0000000000${String(n).padStart(2, '0')}`;

/** Form id -> seeded server category UUID. */
export const SERVER_CATEGORY_IDS: Readonly<Record<string, string>> = {
  food: SEEDED(1), // Food & Dining
  groceries: SEEDED(2), // Groceries
  transport: SEEDED(3), // Travel & Transport
  shopping: SEEDED(4), // Shopping
  utilities: SEEDED(5), // Bills & Utilities
  rent: SEEDED(6), // Rent & Housing
  entertainment: SEEDED(7), // Entertainment
  health: SEEDED(8), // Health
  education: SEEDED(9), // Education
  personal_care: SEEDED(10), // Personal Care
  gifts: SEEDED(11), // Gifts & Donations
  other: SEEDED(12), // Other
};

const FORM_IDS_BY_SERVER_ID: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(SERVER_CATEGORY_IDS).map(([formId, serverId]) => [serverId, formId])
);

/** The UUID to send to the server. Unknown values (already a UUID) pass through. */
export function toServerCategoryId(formId: string): string {
  return SERVER_CATEGORY_IDS[formId] ?? formId;
}

/** The form id for a server category. Unknown values pass through unchanged. */
export function fromServerCategoryId(serverId: string): string {
  return FORM_IDS_BY_SERVER_ID[serverId.toLowerCase()] ?? serverId;
}
