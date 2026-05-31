/**
 * Base API client with error handling, retry logic, and interceptors.
 */

import { APIError, NetworkError } from "../types";

export interface ClientConfig {
  baseURL: string;
  timeout?: number;
  retries?: number;
  retryDelay?: number;
}

declare const process: {
  env: {
    NEXT_PUBLIC_SPORTS_API_URL?: string;
  };
};

export class APIClient {
  private baseURL: string;
  private timeout: number;
  private retries: number;
  private retryDelay: number;

  constructor(config: ClientConfig) {
    this.baseURL = config.baseURL.replace(/\/$/, ""); // Remove trailing slash
    this.timeout = config.timeout ?? 30000; // 30 seconds default
    this.retries = config.retries ?? 2;
    this.retryDelay = config.retryDelay ?? 1000; // 1 second default
  }

  /**
   * Make a request with retry logic and error handling.
   */
  async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= this.retries; attempt++) {
      try {
        // Check if offline
        if (typeof navigator !== "undefined" && !navigator.onLine) {
          throw new NetworkError("You are currently offline. Please check your internet connection.");
        }
        
        const response = await fetch(url, {
          ...options,
          signal: controller.signal,
          headers: {
            "Content-Type": "application/json",
            ...options.headers,
          },
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
          let detail: string | undefined;
          try {
            const errorData = await response.json();
            detail = errorData.detail || errorData.message;
          } catch {
            detail = response.statusText;
          }

          throw new APIError(
            `Request failed: ${response.status} ${response.statusText}`,
            response.status,
            detail
          );
        }

        // Reject non-JSON responses
        const contentType = response.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
          throw new APIError(
            `Expected JSON response but got ${contentType ?? "no content-type"}`,
            response.status,
            `Non-JSON response from ${endpoint}`
          );
        }

        return await response.json();
      } catch (error) {
        clearTimeout(timeoutId);

        // Don't retry on abort (timeout) or client errors (4xx)
        if (
          error instanceof APIError &&
          error.statusCode >= 400 &&
          error.statusCode < 500
        ) {
          throw error;
        }

        // Don't retry on abort
        if (error instanceof Error && error.name === "AbortError") {
          throw new NetworkError("Request timeout", error);
        }

        lastError = error instanceof Error ? error : new Error(String(error));

        // Wait before retrying (exponential backoff)
        if (attempt < this.retries) {
          await this.delay(this.retryDelay * Math.pow(2, attempt));
        }
      }
    }

    // All retries exhausted
    if (lastError instanceof APIError) {
      throw lastError;
    }
    throw new NetworkError("Request failed after retries", lastError);
  }

  /**
   * GET request.
   */
  async get<T>(endpoint: string, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: "GET" });
  }

  /**
   * POST request.
   */
  async post<T>(endpoint: string, data?: unknown, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "POST",
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  /**
   * PUT request.
   */
  async put<T>(endpoint: string, data?: unknown, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: "PUT",
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  /**
   * DELETE request.
   */
  async delete<T>(endpoint: string, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: "DELETE" });
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

/**
 * Create a default API client instance.
 * Uses NEXT_PUBLIC_SPORTS_API_URL or defaults to localhost:8000.
 */
export function createClient(baseURL?: string): APIClient {
  const url =
    baseURL ||
    (typeof window !== "undefined"
      ? process.env.NEXT_PUBLIC_SPORTS_API_URL || "http://localhost:8000"
      : "http://localhost:8000");

  return new APIClient({
    baseURL: url,
    timeout: 30000,
    retries: 2,
    retryDelay: 1000,
  });
}
