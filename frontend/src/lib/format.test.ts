import { describe, expect, it } from 'vitest'
import { errorText, formatSignedMs, formatSignedSeconds, formatUtcTime } from './format'

describe('formatSignedSeconds', () => {
  it('always shows a sign', () => {
    expect(formatSignedSeconds(3.24)).toBe('+3.2 s')
    expect(formatSignedSeconds(-0.56)).toBe('−0.6 s')
    expect(formatSignedSeconds(0)).toBe('±0.0 s')
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
