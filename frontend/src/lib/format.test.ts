import { describe, expect, it } from 'vitest'
import {
  errorText,
  fastOrSlow,
  formatDialTime,
  formatSignedMs,
  formatSignedRate,
  formatSignedSeconds,
  formatUtcTime,
  formatWallTime,
  toLocalIsoString,
} from './format'

describe('formatSignedSeconds', () => {
  it('always shows a sign', () => {
    expect(formatSignedSeconds(3.24)).toBe('+3.2 s')
    expect(formatSignedSeconds(-0.56)).toBe('−0.6 s')
    expect(formatSignedSeconds(0)).toBe('±0.0 s')
  })

  it('signs the value as shown, so a tiny deviation is ±0.0', () => {
    expect(formatSignedSeconds(-0.04)).toBe('±0.0 s')
    expect(formatSignedSeconds(0.04)).toBe('±0.0 s')
    expect(formatSignedSeconds(-0.05)).toBe('−0.1 s')
    expect(formatSignedRate(-0.01)).toBe('±0.0 s/d')
  })
})

describe('fastOrSlow', () => {
  it('follows the shown value: positive is fast, ±0.0 is neither', () => {
    expect(fastOrSlow(1.2)).toBe('fast')
    expect(fastOrSlow(-1.2)).toBe('slow')
    expect(fastOrSlow(0)).toBeNull()
    expect(fastOrSlow(-0.04)).toBeNull()
  })
})

describe('formatSignedMs', () => {
  it('always shows a sign', () => {
    expect(formatSignedMs(94.4)).toBe('+94 ms')
    expect(formatSignedMs(-132)).toBe('−132 ms')
  })
})

describe('formatUtcTime', () => {
  it('shows UTC time with milliseconds', () => {
    expect(formatUtcTime(Date.UTC(2026, 9, 14, 18, 15, 30, 250))).toBe('18:15:30.250')
  })
})

describe('errorText', () => {
  it('drops the Error prefix', () => {
    expect(errorText(new Error('boom'))).toBe('boom')
    expect(errorText('plain')).toBe('plain')
  })
})

describe('toLocalIsoString', () => {
  it('has the local offset and parses back to the same instant', () => {
    const d = new Date(Date.UTC(2026, 9, 18, 18, 15, 30, 250))
    const s = toLocalIsoString(d)
    expect(s).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$/)
    expect(Date.parse(s)).toBe(d.getTime())
  })
})

describe('formatWallTime', () => {
  it('shifts by the offset', () => {
    expect(formatWallTime(Date.UTC(2026, 9, 18, 18, 15, 30, 250), 120)).toBe('20:15:30.2')
  })
})

describe('formatDialTime', () => {
  it('pads and marks withheld seconds', () => {
    expect(formatDialTime(10, 8, 7.04)).toBe('10:08:07.0')
    expect(formatDialTime(12, 0, null)).toBe('12:00:??')
  })
})

describe('formatSignedRate', () => {
  it('shows an explicit sign and s/d', () => {
    expect(formatSignedRate(3.24)).toBe('+3.2 s/d')
    expect(formatSignedRate(-0.06)).toBe('−0.1 s/d')
    expect(formatSignedRate(0)).toBe('±0.0 s/d')
  })
})
