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

export function isOwnerId(value: string): boolean {
  return UUID.test(value)
}

/** This browser's owner ID, created on first use. */
export function ownerId(): string {
  const stored = readStored(KEY)
  if (stored && isOwnerId(stored)) return stored
  fallback ??= crypto.randomUUID()
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
