/**
 * Runs `callback` when the screen gains focus and whenever the app returns to the
 * foreground while the screen is focused (T-36). This is the whole "freshness"
 * mechanism: no polling, websockets or push.
 */

import { useCallback } from 'react';
import { AppState } from 'react-native';
import { useFocusEffect } from 'expo-router';

export function useRefreshOnActive(callback: () => void): void {
  useFocusEffect(
    useCallback(() => {
      callback();
      const subscription = AppState.addEventListener('change', (state) => {
        if (state === 'active') callback();
      });
      return () => subscription.remove();
    }, [callback])
  );
}
