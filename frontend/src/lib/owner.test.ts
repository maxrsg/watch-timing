import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { adoptOwner, isOwnerId, ownerId, ownerLink, resetOwnerFallback } from './owner'

function fakeStorage(): Storage {
  const data = new Map<string, string>()
  return {
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
    clear: () => data.clear(),
    key: () => null,
    get length() {
      return data.size
    },
  }
}

function blockedStorage(): Storage {
  const fail = () => {
    throw new DOMException('blocked', 'SecurityError')
  }
  return { getItem: fail, setItem: fail, removeItem: fail, clear: fail, key: fail, length: 0 }
}

const ID = '0b8f7f0e-4a5c-4f1e-9a42-2f6e3b1c9d10'

beforeEach(() => resetOwnerFallback())
afterEach(() => vi.unstubAllGlobals())

describe('ownerId', () => {
  it('creates an ID once and keeps it', () => {
    vi.stubGlobal('localStorage', fakeStorage())
    const id = ownerId()
    expect(isOwnerId(id)).toBe(true)
    resetOwnerFallback()
    expect(ownerId()).toBe(id)
  })

  it('still works, for the page, when storage is blocked', () => {
    vi.stubGlobal('localStorage', blockedStorage())
    const id = ownerId()
    expect(isOwnerId(id)).toBe(true)
    expect(ownerId()).toBe(id)
  })
})

describe('adoptOwner', () => {
  it('takes over a valid ID', () => {
    vi.stubGlobal('localStorage', fakeStorage())
    ownerId()
    expect(adoptOwner(ID.toUpperCase())).toBe(true)
    expect(ownerId()).toBe(ID)
  })

  it('ignores anything else', () => {
    vi.stubGlobal('localStorage', fakeStorage())
    const id = ownerId()
    expect(adoptOwner('not-an-id')).toBe(false)
    expect(ownerId()).toBe(id)
  })
})

it('builds the owner link', () => {
  vi.stubGlobal('localStorage', fakeStorage())
  adoptOwner(ID)
  expect(ownerLink('https://example.test', '/')).toBe(`https://example.test/#watches?owner=${ID}`)
})
