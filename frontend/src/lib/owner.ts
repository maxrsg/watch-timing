/**
 * There's no login yet: the browser generates an anonymous owner ID, keeps it in localStorage
 * and sends it with every watch request. Whoever has the ID has the watches, so the owner link
 * (which carries it) moves them to another browser. A later login can claim the ID.
 */
import { readStored, writeStored } from '@/lib/storage'

const KEY = 'watchtiming.owner'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** For when storage is blocked: the ID lasts as long as the page. */
let fallback: string | null = null

/**
 * A random UUID v4. `crypto.randomUUID` exists only in secure contexts (HTTPS); without it the
 * same ID is built from `getRandomValues`, which is available everywhere.
 */
export function randomUuid(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6]! & 0x0f) | 0x40 // version 4
  b[8] = (b[8]! & 0x3f) | 0x80 // RFC 4122 variant
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function isOwnerId(value: string): boolean {
  return UUID.test(value)
}

/** This browser's owner ID, created on first use. */
export function ownerId(): string {
  const stored = readStored(KEY)
  if (stored && isOwnerId(stored)) return stored
  fallback ??= randomUuid()
  writeStored(KEY, fallback)
  return fallback
}

/** Take over the owner ID from an owner link. False (and nothing changes) if it isn't one. */
export function adoptOwner(id: string): boolean {
  if (!isOwnerId(id)) return false
  fallback = id.toLowerCase()
  writeStored(KEY, fallback)
  return true
}

/** A link that opens this browser's watches in another browser. */
export function ownerLink(origin: string = window.location.origin, path = window.location.pathname): string {
  return `${origin}${path}#watches?owner=${ownerId()}`
}

/** For tests: forget the in-memory ID. */
export function resetOwnerFallback(): void {
  fallback = null
}
