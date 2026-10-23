import * as SecureStore from 'expo-secure-store';

const STORAGE_KEY = 'smart-expense-auth-session';

export interface StoredAuthSession {
  userId: string;
}

export function initializeSecureStorage(): void {
  // Keep initialization explicit for app bootstrap and future migrations.
}

export async function getStoredAuthSession(): Promise<StoredAuthSession | null> {
  const value = await SecureStore.getItemAsync(STORAGE_KEY);
  if (!value) {
    return null;
  }

  try {
    return JSON.parse(value) as StoredAuthSession;
  } catch {
    await SecureStore.deleteItemAsync(STORAGE_KEY);
    return null;
  }
}

export async function setStoredAuthSession(session: StoredAuthSession): Promise<void> {
  await SecureStore.setItemAsync(STORAGE_KEY, JSON.stringify(session));
}

export async function clearStoredAuthSession(): Promise<void> {
  await SecureStore.deleteItemAsync(STORAGE_KEY);
}
