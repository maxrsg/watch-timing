import { describe, expect, it } from 'vitest'
import { detectPlatform } from './platform'

const IPHONE_FIREFOX =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/144.0 Mobile/15E148 Safari/605.1.15'
const IPAD_DESKTOP_MODE =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15'
const ANDROID_CHROME =
  'Mozilla/5.0 (Linux; Android 16; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Mobile Safari/537.36'

describe('detectPlatform', () => {
  it('detects iPhone in any browser', () => {
    expect(detectPlatform(IPHONE_FIREFOX, 5)).toBe('ios')
  })
  it('treats a touch-capable "Macintosh" as iPadOS', () => {
    expect(detectPlatform(IPAD_DESKTOP_MODE, 5)).toBe('ios')
    expect(detectPlatform(IPAD_DESKTOP_MODE, 0)).toBe('other')
  })
  it('detects Android', () => {
    expect(detectPlatform(ANDROID_CHROME, 5)).toBe('android')
  })
})
