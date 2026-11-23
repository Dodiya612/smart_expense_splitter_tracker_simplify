/**
 * Category metadata for Budget display and forms.
 */

export interface BudgetCategoryMeta {
  id: string; // Server UUID
  formId: string;
  name: string;
  icon: string;
}

const SEEDED = (n: number): string => `00000000-0000-4000-8000-0000000000${String(n).padStart(2, '0')}`;

export const DEFAULT_BUDGET_CATEGORIES: BudgetCategoryMeta[] = [
  { id: SEEDED(1), formId: 'food', name: 'Food & Dining', icon: 'restaurant-outline' },
  { id: SEEDED(2), formId: 'groceries', name: 'Groceries', icon: 'cart-outline' },
  { id: SEEDED(3), formId: 'transport', name: 'Travel & Transport', icon: 'car-outline' },
  { id: SEEDED(4), formId: 'shopping', name: 'Shopping', icon: 'bag-handle-outline' },
  { id: SEEDED(5), formId: 'utilities', name: 'Bills & Utilities', icon: 'flash-outline' },
  { id: SEEDED(6), formId: 'rent', name: 'Rent & Housing', icon: 'home-outline' },
  { id: SEEDED(7), formId: 'entertainment', name: 'Entertainment', icon: 'film-outline' },
  { id: SEEDED(8), formId: 'health', name: 'Health', icon: 'medkit-outline' },
  { id: SEEDED(9), formId: 'education', name: 'Education', icon: 'school-outline' },
  { id: SEEDED(10), formId: 'personal_care', name: 'Personal Care', icon: 'sparkles-outline' },
  { id: SEEDED(11), formId: 'gifts', name: 'Gifts & Donations', icon: 'gift-outline' },
  { id: SEEDED(12), formId: 'other', name: 'Other', icon: 'shapes-outline' },
];

export function getCategoryMeta(categoryId: string | null | undefined): BudgetCategoryMeta | null {
  if (!categoryId) return null;
  const match = DEFAULT_BUDGET_CATEGORIES.find(
    (c) => c.id.toLowerCase() === categoryId.toLowerCase()
  );
  return (
    match ?? {
      id: categoryId,
      formId: categoryId,
      name: 'Custom Category',
      icon: 'pricetag-outline',
    }
  );
}
