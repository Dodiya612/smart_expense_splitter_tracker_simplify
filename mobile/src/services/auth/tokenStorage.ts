import type { AuthUser, TokenBundle } from '../api/types';



export interface KeyValueStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  deleteItem(key: string): Promise<void>;
}

// In-memory storage engine (default fallback for testing and non-native runtimes)
class MemoryStorage implements KeyValueStorage {
  private map = new Map<string, string>();

  async getItem(key: string): Promise<string | null> {
    return this.map.get(key) ?? null;
  }

  async setItem(key: string, value: string): Promise<void> {
    this.map.set(key, value);
  }

  async deleteItem(key: string): Promise<void> {
    this.map.delete(key);
  }

  clear(): void {
    this.map.clear();
  }
}

export const defaultMemoryStorage = new MemoryStorage();

let activeStorage: KeyValueStorage = defaultMemoryStorage;

export function setStorageAdapter(adapter: KeyValueStorage): void {
  activeStorage = adapter;
}

export function getStorageAdapter(): KeyValueStorage {
  return activeStorage;
}

const ACCESS_TOKEN_KEY = 'splittr_auth_access_token';
const REFRESH_TOKEN_KEY = 'splittr_auth_refresh_token';
const USER_KEY = 'splittr_auth_user_cache';

export const tokenStorage = {
  setStorageAdapter,

  /**
   * Securely saves the access and refresh token pair.
   */
  async saveTokens(tokens: TokenBundle): Promise<void> {
    if (tokens.accessToken) {
      await activeStorage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken);
    }
    if (tokens.refreshToken) {
      await activeStorage.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken);
    }
  },

  /**
   * Retrieves the current stored access token.
   */
  async getAccessToken(): Promise<string | null> {
    return await activeStorage.getItem(ACCESS_TOKEN_KEY);
  },

  /**
   * Retrieves the current stored refresh token.
   */
  async getRefreshToken(): Promise<string | null> {
    return await activeStorage.getItem(REFRESH_TOKEN_KEY);
  },

  /**
   * Saves the cached user profile for instant cold-start display.
   */
  async saveUser(user: AuthUser): Promise<void> {
    await activeStorage.setItem(USER_KEY, JSON.stringify(user));
  },

  /**
   * Retrieves the cached user profile if available.
   */
  async getUser(): Promise<AuthUser | null> {
    const raw = await activeStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as AuthUser;
    } catch {
      return null;
    }
  },

  /**
   * Clears all stored tokens and cached user data.
   */
  async clearAll(): Promise<void> {
    await Promise.all([
      activeStorage.deleteItem(ACCESS_TOKEN_KEY),
      activeStorage.deleteItem(REFRESH_TOKEN_KEY),
      activeStorage.deleteItem(USER_KEY),
    ]);
  },
};
