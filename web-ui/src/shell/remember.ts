/**
 * A choice the page keeps between visits.
 *
 * Storage can be blocked -- private mode, a locked-down profile -- and a
 * preference that cannot be saved is not an error worth showing anybody, so
 * both halves swallow it and the page carries on with its default.
 */

export function recall(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

export function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // nothing to say: the page works, it just will not remember
  }
}
