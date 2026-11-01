import { describe, expect, it } from 'vitest'
import type { DialReading, ReadResult } from '@/api/client'
import { measurementFromResult } from './measurement'

const reading: DialReading = {
  hours: 10,
  minutes: 8,
  seconds: 37,
  confidence: 0.9,
  seconds_confidence: 0.8,
  needs_confirmation: false,
  reasons: [],
  correction: null,
}

const result: ReadResult = {
  image_width: 100,
  image_height: 100,
  reference_time_utc: '2026-10-18T08:08:34.500Z',
  reference_utc_offset_minutes: 120,
  reference_source: 'device_clock',
  frame_timing: 'capture_time',
  platform: 'ios',
  latency_correction_ms: 132,
  timestamp_error: null,
  image_sha256: 'ab'.repeat(32),
  expected_deviation_s: null,
  reading,
  overlay: null,
  reading_error: null,
  deviation_s: 2.5,
}

describe('measurementFromResult', () => {
  it('carries the reading, the reference and the tap', () => {
    expect(measurementFromResult(result, { x: 1, y: 2 })).toEqual({
      reference_time_utc: '2026-10-18T08:08:34.500Z',
      reference_utc_offset_minutes: 120,
      reference_source: 'device_clock',
      platform: 'ios',
      frame_timing: 'capture_time',
      latency_correction_ms: 132,
      hours: 10,
      minutes: 8,
      seconds: 37,
      confidence: 0.9,
      seconds_confidence: 0.8,
      correction: null,
      overlay: null,
      tap: { x: 1, y: 2 },
      image_sha256: 'ab'.repeat(32),
    })
  })

  it('needs the seconds and a reference time', () => {
    expect(measurementFromResult({ ...result, reading: { ...reading, seconds: null } }, null)).toBeNull()
    expect(measurementFromResult({ ...result, reading: null }, null)).toBeNull()
    expect(measurementFromResult({ ...result, reference_time_utc: null }, null)).toBeNull()
  })
})
