/**
 * T-23b / US-26 – Suggestion API stub.
 *
 * The real endpoint is  POST /api/v1/suggestions  (implemented by T-23).
 * This stub simulates the three-layer pipeline described in US-26:
 *   Layer 1 – user-history match (fastest, < 5 ms)
 *   Layer 2 – on-server TF-IDF + logistic regression (< 50 ms)
 *   Layer 3 – LLM fallback when classifier confidence < 60 %
 *
 * `fetchCategorySuggestion` is debounced at the call-site (useCategorySuggestion);
 * this function itself makes one API request per call.
 *
 * The user's final choice is posted back via `postSuggestionFeedback` so the
 * first-layer user-history improves over time (US-26).
 */

import type { SuggestionFeedback, SuggestionResponse } from '../types';

// ── Types ─────────────────────────────────────────────────────────────────────

// Re-exported from types; declared here for documentation proximity.
export type { SuggestionResponse, SuggestionFeedback };

// ── Stub ──────────────────────────────────────────────────────────────────────

/** Simple keyword → category map used by the stub. */
const KEYWORD_MAP: Record<string, string> = {
  uber: 'transport',
  ola: 'transport',
  auto: 'transport',
  metro: 'transport',
  bus: 'transport',
  train: 'transport',
  flight: 'travel',
  hotel: 'travel',
  zomato: 'food',
  swiggy: 'food',
  restaurant: 'food',
  coffee: 'food',
  cafe: 'food',
  pizza: 'food',
  dinner: 'food',
  lunch: 'food',
  grocery: 'groceries',
  bigbasket: 'groceries',
  blinkit: 'groceries',
  zepto: 'groceries',
  pharmacy: 'health',
  doctor: 'health',
  hospital: 'health',
  medicine: 'health',
  movie: 'entertainment',
  netflix: 'entertainment',
  spotify: 'entertainment',
  game: 'entertainment',
  electricity: 'utilities',
  wifi: 'utilities',
  internet: 'utilities',
  rent: 'utilities',
  amazon: 'shopping',
  flipkart: 'shopping',
  clothes: 'shopping',
};

function stubClassify(description: string): { categoryId: string; confidence: number } {
  const lower = description.toLowerCase();
  for (const [keyword, categoryId] of Object.entries(KEYWORD_MAP)) {
    if (lower.includes(keyword)) {
      return { categoryId, confidence: 0.82 };
    }
  }
  return { categoryId: 'other', confidence: 0.45 };
}

export async function fetchCategorySuggestion(
  description: string
): Promise<SuggestionResponse | null> {
  if (!description.trim()) return null;

  // TODO: replace with  POST /api/v1/suggestions  { description }
  await new Promise((r) => setTimeout(r, 120)); // simulate < 200 ms

  const { categoryId, confidence } = stubClassify(description);

  return {
    categoryId,
    confidence,
    // source indicates which pipeline layer answered (for analytics).
    source: confidence >= 0.6 ? 'classifier' : 'llm',
  };
}

export async function postSuggestionFeedback(
  feedback: SuggestionFeedback
): Promise<void> {
  // TODO: replace with  POST /api/v1/suggestions/feedback  { ... }
  // Fire-and-forget; never blocks the form save.
  await new Promise((r) => setTimeout(r, 0));
  // In production: fetch('/api/v1/suggestions/feedback', { method:'POST', body: JSON.stringify(feedback) })
}
