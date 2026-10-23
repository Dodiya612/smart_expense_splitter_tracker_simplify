/**
 * Coinscious API Client runtime implementation.
 */
export class CoinsciousClient {
  constructor(options = {}) {
    this.baseUrl = (options.baseUrl || "http://localhost:8000").replace(/\/+$/, "");
    this.fetchFn = options.fetch || globalThis.fetch.bind(globalThis);
    this.defaultHeaders = {
      Accept: "application/json",
      ...(options.headers || {}),
    };

    this.health = {
      check: async (customHeaders) => {
        return this.request("/api/v1/health", {
          method: "GET",
          headers: customHeaders,
        });
      },

      get: async (customHeaders) => {
        return this.health.check(customHeaders);
      },
    };
  }

  async request(path, options = {}) {
    const url = `${this.baseUrl}${path.startsWith("/") ? "" : "/"}${path}`;
    const headers = {
      ...this.defaultHeaders,
      ...(options.headers || {}),
    };

    let bodyData = undefined;
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
      let errorData;
      try {
        errorData = await response.json();
      } catch {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      throw errorData;
    }

    return await response.json();
  }
}

export function createCoinsciousClient(options) {
  return new CoinsciousClient(options);
}
