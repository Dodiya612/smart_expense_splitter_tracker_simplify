/**
 * Type-safe Coinscious API Client generated from OpenAPI specification.
 */
import type { components, paths } from "./schema.js";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type ErrorResponse = components["schemas"]["ErrorResponse"];
export type ErrorDetails = components["schemas"]["ErrorDetails"];
export type ErrorMeta = components["schemas"]["ErrorMeta"];

export interface ClientOptions {
  /** Base URL for Coinscious Backend API (default: http://localhost:8000) */
  baseUrl?: string;
  /** Custom fetch implementation (defaults to global fetch) */
  fetch?: typeof fetch;
  /** Default request headers */
  headers?: Record<string, string>;
}

export interface RequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
}

export class CoinsciousClient {
  public readonly baseUrl: string;
  private readonly fetchFn: typeof fetch;
  private readonly defaultHeaders: Record<string, string>;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = (options.baseUrl || "http://localhost:8000").replace(/\/+$/, "");
    this.fetchFn = options.fetch || globalThis.fetch.bind(globalThis);
    this.defaultHeaders = {
      Accept: "application/json",
      ...(options.headers || {}),
    };
  }

  /**
   * Generic request helper with automatic ErrorResponse unwrapping.
   */
  public async request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith("/") ? "" : "/"}${path}`;
    const headers: Record<string, string> = {
      ...this.defaultHeaders,
      ...(options.headers || {}),
    };

    let bodyData: BodyInit | undefined = undefined;
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      bodyData = JSON.stringify(options.body);
    }

    const response = await this.fetchFn(url, {
      method: options.method || "GET",
      headers,
      body: bodyData,
    });

    if (!response.ok) {
      let errorData: ErrorResponse;
      try {
        errorData = (await response.json()) as ErrorResponse;
      } catch {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      throw errorData;
    }

    return (await response.json()) as T;
  }

  /**
   * Health endpoints family.
   */
  public readonly health = {
    /**
     * Call GET /api/v1/health liveness probe.
     * @returns Promise<HealthResponse> on success
     * @throws ErrorResponse on API failure
     */
    check: async (customHeaders?: Record<string, string>): Promise<HealthResponse> => {
      return this.request<HealthResponse>("/api/v1/health", {
        method: "GET",
        headers: customHeaders,
      });
    },

    /**
     * Alias for check().
     */
    get: async (customHeaders?: Record<string, string>): Promise<HealthResponse> => {
      return this.health.check(customHeaders);
    },
  };
}

/**
 * Factory function to create a new Coinscious API client instance.
 */
export function createCoinsciousClient(options?: ClientOptions): CoinsciousClient {
  return new CoinsciousClient(options);
}
