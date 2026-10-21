import { describe, expect, it } from 'vitest'
import type { Overlay } from '@/api/client'
import { clockPoint, initialTip, initialTips } from './hands'

const overlay = (hands: Overlay['hands'] = []): Overlay => ({
  dial_center: { x: 500, y: 500 },
  dial_semi_major: 100,
  dial_semi_minor: 90,
  dial_angle_deg: 0,
  pivot: { x: 500, y: 500 },
  twelve: { x: 500, y: 410 },
  hands,
})

describe('clockPoint', () => {
  it('measures clockwise from 12 with y pointing down', () => {
    const origin = { x: 10, y: 10 }
    const near = (p: { x: number; y: number }, x: number, y: number) => {
      expect(p.x).toBeCloseTo(x)
      expect(p.y).toBeCloseTo(y)
    }
    near(clockPoint(origin, 0, 5), 10, 5)
    near(clockPoint(origin, 90, 5), 15, 10)
    near(clockPoint(origin, 180, 5), 10, 15)
    near(clockPoint(origin, 270, 5), 5, 10)
  })
})

describe('initialTips', () => {
  it('starts at the detected hands', () => {
    const tip = { x: 520, y: 430 }
    expect(initialTip(overlay([{ role: 'minute', tip }]), 'minute')).toEqual(tip)
  })

  it('starts missing hands at their defaults around the pivot', () => {
    const tips = initialTips(overlay([{ role: 'other', tip: { x: 0, y: 0 } }]))
    // Minute default: 2 o'clock (60°), 0.75 of the dial ring.
    expect(tips.minute.x).toBeCloseTo(500 + 75 * Math.sin(Math.PI / 3))
    expect(tips.minute.y).toBeCloseTo(500 - 75 * Math.cos(Math.PI / 3))
    // Seconds default: straight down.
    expect(tips.second?.x).toBeCloseTo(500)
    expect(tips.second?.y).toBeCloseTo(580)
  })
})
