import { describe, expect, it } from 'vitest'
import type { ReadResult } from '@/api/client'
import { typedTimePlaceholders, parseTypedTime } from './typed-time'

const fields = (hours: string, minutes: string, seconds: string) => ({ hours, minutes, seconds })

describe('parseTypedTime', () => {
  it('parses whole hours and minutes and decimal seconds', () => {
    expect(parseTypedTime(fields('10', '08', '37.5'))).toEqual({ hours: 10, minutes: 8, seconds: 37.5 })
    expect(parseTypedTime(fields(' 12 ', '0', '0'))).toEqual({ hours: 12, minutes: 0, seconds: 0 })
  })

  it('accepts a comma as the decimal separator', () => {
    expect(parseTypedTime(fields('1', '2', '3,4'))).toEqual({ hours: 1, minutes: 2, seconds: 3.4 })
  })

  it('rejects missing and out-of-range fields', () => {
    expect(parseTypedTime(fields('10', '8', ''))).toMatch(/Enter/)
    expect(parseTypedTime(fields('0', '8', '1'))).toMatch(/Hours/)
    expect(parseTypedTime(fields('13', '8', '1'))).toMatch(/Hours/)
    expect(parseTypedTime(fields('10', '60', '1'))).toMatch(/Minutes/)
    expect(parseTypedTime(fields('10', '8.5', '1'))).toMatch(/Minutes/)
    expect(parseTypedTime(fields('10', '8', '60'))).toMatch(/Seconds/)
    expect(parseTypedTime(fields('10', '8', '-1'))).toMatch(/Seconds/)
    expect(parseTypedTime(fields('10', '8', '1e1'))).toMatch(/Seconds/)
  })
})

function result(partial: Partial<ReadResult>): ReadResult {
  return {
    image_width: 1,
    image_height: 1,
    reference_time_utc: null,
    reference_utc_offset_minutes: null,
    reference_source: null,
    latency_correction_ms: null,
    timestamp_error: null,
    reading: null,
    overlay: null,
    reading_error: null,
    deviation_s: null,
    ...partial,
  }
}

describe('typedTimePlaceholders', () => {
  it('shows the format without a result', () => {
    expect(typedTimePlaceholders(null)).toEqual(fields('h', 'mm', 'ss.s'))
  })

  it('starts from the reading', () => {
    const reading = {
      hours: 10,
      minutes: 8,
      seconds: 37.04,
      confidence: 0.5,
      seconds_confidence: 0.5,
      needs_confirmation: true,
      reasons: [],
      correction: null,
    }
    expect(typedTimePlaceholders(result({ reading }))).toEqual(fields('10', '08', '37.0'))
    expect(typedTimePlaceholders(result({ reading: { ...reading, seconds: null } }))).toEqual(fields('10', '08', 'ss.s'))
  })

  it("starts from the reference's hour and minute in the watch's zone, never its seconds", () => {
    const r = result({ reference_time_utc: '2026-10-18T22:05:30.000Z', reference_utc_offset_minutes: 120 })
    expect(typedTimePlaceholders(r)).toEqual(fields('12', '05', 'ss.s'))
  })
})
