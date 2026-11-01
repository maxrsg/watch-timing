/**
 * localStorage that never throws: it can be missing or blocked (private windows, cleared or
 * blocked site data). Only for per-browser conveniences; callers must cope with null.
 */
export function readStored(key: string): string | null {
  try {
    return globalThis.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) globalThis.localStorage.removeItem(key)
    else globalThis.localStorage.setItem(key, value)
  } catch {
    // Not stored; the value lives only as long as the page.
  }
}
