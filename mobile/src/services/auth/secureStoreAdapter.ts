import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import { KeyValueStorage, setStorageAdapter } from './tokenStorage';

export class SecureStoreAdapter implements KeyValueStorage {
  async getItem(key: string): Promise<string | null> {
    if (Platform.OS === 'web') {
      try {
        if (typeof window !== 'undefined' && window.localStorage) {
          return window.localStorage.getItem(key);
        }
      } catch {
        // Fallback to null
      }
      return null;
    }

    return await SecureStore.getItemAsync(key);
  }

  async setItem(key: string, value: string): Promise<void> {
    if (Platform.OS === 'web') {
      try {
        if (typeof window !== 'undefined' && window.localStorage) {
          window.localStorage.setItem(key, value);
          return;
        }
      } catch {
        // Fallback
      }
      return;
    }

    await SecureStore.setItemAsync(key, value, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED,
    });
  }

  async deleteItem(key: string): Promise<void> {
    if (Platform.OS === 'web') {
      try {
        if (typeof window !== 'undefined' && window.localStorage) {
          window.localStorage.removeItem(key);
          return;
        }
      } catch {
        // Fallback
      }
      return;
    }

    await SecureStore.deleteItemAsync(key);
  }
}

let isInitialized = false;

export function initializeSecureStorage(): void {
  if (!isInitialized) {
    setStorageAdapter(new SecureStoreAdapter());
    isInitialized = true;
  }
}
