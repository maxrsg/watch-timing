import { describe, expect, it } from 'vitest'
import { sampleFromRoundTrip } from './clock'
import { wallClock } from './frame'

describe('sampleFromRoundTrip', () => {
  it('assumes the server answered halfway through the round trip', () => {
    // Device sends at 1000, server says 1550, device receives at 1100 → server is 500 ms ahead.
    expect(sampleFromRoundTrip(1000, 1550, 1100)).toEqual({ offsetMs: 500, rttMs: 100 })
  })
  it('gives a negative offset when the device is ahead', () => {
    expect(sampleFromRoundTrip(2000, 1800, 2000).offsetMs).toBe(-200)
  })
})

describe('wallClock', () => {
  it('maps a high-res timestamp relative to the current wall/perf pair', () => {
    // perf 5000 ↔ wall 1_000_000; a frame at perf 4900 happened 100 ms earlier.
    expect(wallClock(4900, 1_000_000, 5000).getTime()).toBe(999_900)
  })
})
