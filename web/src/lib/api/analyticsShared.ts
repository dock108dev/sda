import { getApiBase } from "./apiBase";

export const base = () => getApiBase();

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.error || body.message || JSON.stringify(body);
    } catch {
      // body wasn't JSON -- keep statusText
    }
    throw new Error(`API error: ${res.status} -- ${detail}`);
  }
  return res.json() as Promise<T>;
}
