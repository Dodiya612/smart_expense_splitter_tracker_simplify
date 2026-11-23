/**
 * Categories for group expenses (T-31 / US-18, US-19).
 *
 * The shared expense API needs a category UUID. There is no categories endpoint
 * yet, so these are the 12 default categories seeded with fixed ids by
 * backend/alembic/versions/004_create_expenses_and_categories.py.
 * Replace with an API call once GET /api/v1/categories exists.
 */

export interface GroupExpenseCategory {
  id: string;
  label: string;
}

export const GROUP_EXPENSE_CATEGORIES: readonly GroupExpenseCategory[] = [
  { id: '00000000-0000-4000-8000-000000000001', label: 'Food & Dining' },
  { id: '00000000-0000-4000-8000-000000000002', label: 'Groceries' },
  { id: '00000000-0000-4000-8000-000000000003', label: 'Travel & Transport' },
  { id: '00000000-0000-4000-8000-000000000004', label: 'Shopping' },
  { id: '00000000-0000-4000-8000-000000000005', label: 'Bills & Utilities' },
  { id: '00000000-0000-4000-8000-000000000006', label: 'Rent & Housing' },
  { id: '00000000-0000-4000-8000-000000000007', label: 'Entertainment' },
  { id: '00000000-0000-4000-8000-000000000008', label: 'Health' },
  { id: '00000000-0000-4000-8000-000000000009', label: 'Education' },
  { id: '00000000-0000-4000-8000-000000000010', label: 'Personal Care' },
  { id: '00000000-0000-4000-8000-000000000011', label: 'Gifts & Donations' },
  { id: '00000000-0000-4000-8000-000000000012', label: 'Other' },
];
