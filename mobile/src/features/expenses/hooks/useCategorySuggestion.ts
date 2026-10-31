/**
 * useCategorySuggestion – T-23b / US-26
 *
 * Debounces the description input by 400 ms (per US-26 spec) then calls the
 * suggestion API.  Returns the current suggestion state.
 *
 * Rules enforced:
 *  - Input debounced 400 ms; clears instantly on empty input.
 *  - Never blocks saving: errors are swallowed (suggestion is best-effort).
 *  - `accept(categoryId)` and `override(categoryId)` both post feedback so the
 *    user-history layer improves.
 *  - Suggestion is cleared whenever the user manually selects a category, or
 *    when the notes/description field is cleared.
 *
 * Usage:
 *   const { suggestion, isLoading, accept, override, dismiss } =
 *     useCategorySuggestion({ description: values.notes, currentCategoryId: values.categoryId });
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchCategorySuggestion, postSuggestionFeedback } from '../services/suggestionApi';
import type { SuggestionResponse } from '../types';

const DEBOUNCE_MS = 400;

export interface UseCategorySuggestionOptions {
  /** The free-text description the user is typing (the Notes field, US-26). */
  description: string;
  /** The category currently selected so we can decide whether to show the chip. */
  currentCategoryId: string;
}

export interface UseCategorySuggestionReturn {
  /** The latest suggestion from the API, or null. */
  suggestion: SuggestionResponse | null;
  /** True while a debounced request is in flight. */
  isLoading: boolean;
  /**
   * Call when the user taps "Accept" on the suggestion chip.
   * Posts feedback (accepted = true) and clears the chip.
   * Returns the accepted categoryId so the caller can update the form.
   */
  accept: () => string | null;
  /**
   * Call when the user manually picks a category that differs from the suggestion.
   * Posts feedback (accepted = false) and clears the chip.
   */
  override: (chosenCategoryId: string) => void;
  /** Dismiss the chip without sending feedback (e.g. user clears the field). */
  dismiss: () => void;
}

export function useCategorySuggestion({
  description,
  currentCategoryId,
}: UseCategorySuggestionOptions): UseCategorySuggestionReturn {
  const [suggestion, setSuggestion] = useState<SuggestionResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Keep the last description that produced a suggestion for feedback.
  const lastDescriptionRef = useRef<string>('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Clear previous debounce
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!description.trim()) {
      setSuggestion(null);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);

    debounceRef.current = setTimeout(async () => {
      try {
        const result = await fetchCategorySuggestion(description);
        lastDescriptionRef.current = description;

        if (result) {
          // Only show if the suggestion differs from what's already selected.
          if (result.categoryId !== currentCategoryId) {
            setSuggestion(result);
          } else {
            setSuggestion(null);
          }
        } else {
          setSuggestion(null);
        }
      } catch {
        // Never block the form on a suggestion error (US-26).
        setSuggestion(null);
      } finally {
        setIsLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [description]);

  const accept = useCallback((): string | null => {
    if (!suggestion) return null;
    const accepted = suggestion.categoryId;

    // Fire-and-forget feedback (never blocks saving).
    postSuggestionFeedback({
      description: lastDescriptionRef.current,
      suggestedCategoryId: suggestion.categoryId,
      chosenCategoryId: accepted,
      accepted: true,
    }).catch(() => {});

    setSuggestion(null);
    return accepted;
  }, [suggestion]);

  const override = useCallback(
    (chosenCategoryId: string) => {
      if (!suggestion) return;

      postSuggestionFeedback({
        description: lastDescriptionRef.current,
        suggestedCategoryId: suggestion.categoryId,
        chosenCategoryId,
        accepted: false,
      }).catch(() => {});

      setSuggestion(null);
    },
    [suggestion]
  );

  const dismiss = useCallback(() => {
    setSuggestion(null);
  }, []);

  return { suggestion, isLoading, accept, override, dismiss };
}
