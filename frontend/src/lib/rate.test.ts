import { describe, expect, it } from 'vitest'
import type { Rate } from '@/api/client'
import { rateNotes } from './rate'

const rate: Rate = {
  rate_s_per_day: 3,
  intercepts: { exif: 0 },
  epoch: '2026-10-20T08:00:00.000Z',
  n: 3,
  span_hours: 48,
  residual_std_s: 0.2,
  short_span: false,
  mixed_sources: false,
}

describe('rateNotes', () => {
  it('says what is missing before there is a rate', () => {
    expect(rateNotes(null, 0)).toEqual(['Save a reading to start.'])
    expect(rateNotes(null, 1)[0]).toMatch(/second measurement/)
  })

  it('flags a short span and mixed sources', () => {
    expect(rateNotes(rate, 3)).toEqual([])
    expect(rateNotes({ ...rate, short_span: true, mixed_sources: true }, 3)).toHaveLength(2)
  })
})
