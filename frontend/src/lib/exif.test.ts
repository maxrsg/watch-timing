import { describe, expect, it } from 'vitest'
import { compareField } from './exif'

describe('compareField', () => {
  it('matches equal values regardless of type', () => {
    expect(compareField(6, '6')).toBe('ok')
    expect(compareField('+02:00', '+02:00')).toBe('ok')
  })
  it('flags missing on either side', () => {
    expect(compareField(null, '123')).toBe('missing')
    expect(compareField('123', null)).toBe('missing')
  })
  it('flags differences', () => {
    expect(compareField('123', '124')).toBe('mismatch')
  })
})

